from __future__ import annotations

import hashlib
import os

import psycopg
import pytest
from tools.work.import_legacy import import_snapshot, reconcile_snapshot
from work_platform.migration import MigrationError

from octop.infra.db.pool import PostgresPool
from octop.infra.work.control_plane import WorkControlPlane
from tests.integration.test_postgresql_control_plane import _reset_public_schema
from tests.support.postgresql import requires_postgresql
from tests.unit.work.test_legacy_migration import snapshot


@requires_postgresql
@pytest.mark.postgresql
def test_legacy_import_resumes_idempotently_and_reconciles_each_object(tmp_path):
    url = os.environ["OCTOP_TEST_DATABASE_URL"]
    pool = PostgresPool(url)
    try:
        _reset_public_schema(pool)
    finally:
        pool.close()
    control = WorkControlPlane(url, "migration-owner")
    control.close()
    (tmp_path / "private").mkdir()
    (tmp_path / "private/f").write_bytes(b"data")
    source = snapshot()
    hashes = {"private/f": hashlib.sha256(b"data").hexdigest()}
    with pytest.raises(InterruptedError):
        import_snapshot(url, source, tmp_path, hashes, tmp_path / "target", stop_after=3)
    with psycopg.connect(url) as db:
        assert db.execute("SELECT count(*) FROM work_legacy_records").fetchone() == (3,)
    result = import_snapshot(url, source, tmp_path, hashes, tmp_path / "target")
    assert result["state"] == "IMPORTED_NOT_ACTIVATED"
    assert result["identity_mapping"] == "NOT_RUN"
    assert (
        import_snapshot(url, source, tmp_path, hashes, tmp_path / "target")["source_digest"]
        == result["source_digest"]
    )
    assert (
        reconcile_snapshot(url, source, tmp_path, hashes, tmp_path / "target")["integrity"]
        == "PASS"
    )
    with psycopg.connect(url) as db:
        assert db.execute(
            "SELECT role,status FROM work_memberships WHERE organization_id='a'"
        ).fetchone() == ("member", "suspended")
        assert db.execute(
            "SELECT scope_id,used FROM work_budget_counters WHERE scope_kind='task'"
        ).fetchone() == ("t", 20)
        assert db.execute("SELECT count(*) FROM work_runs").fetchone() == (0,)
        db.execute(
            "UPDATE work_legacy_records SET payload=jsonb_set(payload,'{content}','\"tampered\"') WHERE source_table='workMessages'"
        )
    assert (
        reconcile_snapshot(url, source, tmp_path, hashes, tmp_path / "target")["integrity"]
        == "FAIL"
    )
    with pytest.raises(MigrationError, match="existing source mapping differs"):
        import_snapshot(url, source, tmp_path, hashes, tmp_path / "target")


@requires_postgresql
@pytest.mark.postgresql
@pytest.mark.parametrize("conflict", ["user", "membership", "quota"])
def test_import_rejects_conflicting_authority_without_overwrite_or_activation(tmp_path, conflict):
    url = os.environ["OCTOP_TEST_DATABASE_URL"]
    pool = PostgresPool(url)
    try:
        _reset_public_schema(pool)
    finally:
        pool.close()
    WorkControlPlane(url, "migration-owner").close()
    (tmp_path / "private").mkdir()
    (tmp_path / "private/f").write_bytes(b"data")
    source = snapshot()
    hashes = {"private/f": hashlib.sha256(b"data").hexdigest()}
    with psycopg.connect(url) as db:
        if conflict == "user":
            db.execute("INSERT INTO work_users VALUES('legacy:1','disabled')")
        elif conflict == "membership":
            db.execute("INSERT INTO work_users VALUES('legacy:1','active')")
            db.execute("INSERT INTO work_memberships VALUES('a','legacy:1','owner','active',9)")
        else:
            db.execute("INSERT INTO work_budget_counters VALUES('task','t','2026-09-29',19)")
    with pytest.raises(MigrationError, match="existing authority differs"):
        import_snapshot(url, source, tmp_path, hashes, tmp_path / "target")
    with psycopg.connect(url) as db:
        assert db.execute("SELECT state FROM work_legacy_batches").fetchone() == ("importing",)
        assert db.execute("SELECT count(*) FROM work_runs").fetchone() == (0,)
        if conflict == "user":
            assert db.execute("SELECT status FROM work_users").fetchone() == ("disabled",)
        elif conflict == "membership":
            assert db.execute("SELECT role,status,revision FROM work_memberships").fetchone() == (
                "owner",
                "active",
                9,
            )
        else:
            assert db.execute("SELECT used FROM work_budget_counters").fetchone() == (19,)
