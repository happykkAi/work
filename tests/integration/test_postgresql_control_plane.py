"""Gated PostgreSQL control-plane integration tests.

Set ``OCTOP_TEST_DATABASE_URL`` to a **dedicated** database (tests DROP SCHEMA public).
Example::

    export OCTOP_TEST_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:15432/octop_test'

Avoid pointing at a shared app DB (locks from other sessions will hang resets).
Without the env var these tests are skipped — default CI stays SQLite-only.
"""

from __future__ import annotations

import os
import shutil
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.support.postgresql import requires_postgresql


def _conninfo() -> str:
    return os.environ["OCTOP_TEST_DATABASE_URL"]


def _consume_handoff_process(args):
    from octop.infra.work.control_plane import WorkControlPlane

    conninfo, binding, handoff = args
    control = WorkControlPlane(conninfo, binding.runtime_id, expected_runtime_binding=binding)
    try:
        return os.getpid(), control.consume_runtime_handoff(handoff) is not None
    finally:
        control.close()


def _reset_public_schema(pool: object) -> None:
    with pool.connect() as conn:  # type: ignore[attr-defined]
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
        conn.execute("COMMIT")


def _pg_payload_from_url(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    return {
        "driver": "postgresql",
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "database": (parsed.path or "/octop").lstrip("/") or "octop",
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "url": url,
    }


@requires_postgresql
@pytest.mark.postgresql
def test_current_work_schema_starts_with_dml_only_role() -> None:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import PostgresPool
    from octop.infra.work.control_plane import WorkControlPlane

    role = "work_test_" + uuid.uuid4().hex
    password = uuid.uuid4().hex
    setup = PostgresPool(_conninfo())
    try:
        _reset_public_schema(setup)
        run_migrations(setup)
    finally:
        setup.close()
    owner = WorkControlPlane(_conninfo(), "migration-owner")
    owner.close()
    with psycopg.connect(_conninfo(), autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        try:
            admin.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
            )
            admin.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
                ).format(sql.Identifier(role))
            )
            restricted = make_conninfo(_conninfo(), user=role, password=password)
            pool = PostgresPool(restricted)
            try:
                run_migrations(pool)
                from octop.infra.db.repos.settings import SettingsRepo

                settings = SettingsRepo(pool)
                settings.revoke_session("expired-test", 1, 0)
                settings.revoke_session("live-test", 100, 2)
                assert settings.get("auth.revoked.expired-test") is None
                assert settings.get("auth.revoked.live-test") == "100"
            finally:
                pool.close()
            control = WorkControlPlane(restricted, "restricted-runtime")
            control.close()
            with psycopg.connect(restricted, autocommit=True) as runtime:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute("CREATE TABLE public.forbidden_runtime_ddl(id INTEGER)")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute("ALTER TABLE work_schema_version ADD COLUMN forbidden INTEGER")
        finally:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@requires_postgresql
@pytest.mark.postgresql
def test_pg_migrate_and_user_roundtrip() -> None:
    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import PostgresPool
    from octop.infra.db.repos.users import UserRepo

    pool = PostgresPool(_conninfo())
    try:
        _reset_public_schema(pool)
        run_migrations(pool)
        repo = UserRepo(pool)
        username = f"pg_tester_{uuid.uuid4().hex[:8]}"
        uid = repo.create(username=username, password_hash="x", role="user")
        row = repo.get(uid)
        assert row is not None
        assert row.username == username
    finally:
        pool.close()


@requires_postgresql
@pytest.mark.postgresql
def test_pg_control_plane_repo_smoke() -> None:
    """Exercise the main control-plane repos on a live PG schema."""
    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import PostgresPool
    from octop.infra.db.repos.agents import AgentRepo
    from octop.infra.db.repos.channels import ChannelRepo
    from octop.infra.db.repos.cron import CronJobRepo
    from octop.infra.db.repos.providers import ProviderRepo
    from octop.infra.db.repos.sessions import SessionRepo
    from octop.infra.db.repos.threads import ThreadRepo
    from octop.infra.db.repos.users import UserRepo
    from octop.infra.gateway.threads import ThreadRegistry
    from octop.infra.utils.ulid import new_ulid

    pool = PostgresPool(_conninfo())
    try:
        _reset_public_schema(pool)
        run_migrations(pool)

        users = UserRepo(pool)
        uid = users.create(username=f"u_{uuid.uuid4().hex[:8]}", password_hash="h", role="admin")
        aid = new_ulid()
        AgentRepo(pool).create(agent_id=aid, user_id=uid, name="bot")
        assert AgentRepo(pool).get(aid) is not None

        cid = new_ulid()
        ChannelRepo(pool).create(
            channel_id=cid,
            agent_id=aid,
            user_id=uid,
            kind="slack",
            name="main",
            config_json="{}",
        )
        assert ChannelRepo(pool).get(cid) is not None

        sk = ThreadRegistry.dashboard_key(agent_id=aid, user_id=uid)
        tid = f"thr_{uuid.uuid4().hex[:10]}"
        ThreadRepo(pool).insert(
            thread_id=tid,
            agent_id=aid,
            user_id=uid,
            channel_type="dashboard",
            session_key=sk,
        )
        SessionRepo(pool).upsert(
            session_key=sk,
            agent_id=aid,
            user_id=uid,
            channel_type="dashboard",
            chat_type="dm",
            thread_id=tid,
        )
        assert SessionRepo(pool).get(sk) is not None
        assert ThreadRepo(pool).get(tid) is not None

        cron_id = new_ulid()
        CronJobRepo(pool).create(
            cron_id=cron_id,
            agent_id=aid,
            user_id=uid,
            trigger="0 9 * * *",
            prompt="ping",
            session_key=sk,
        )
        assert CronJobRepo(pool).get(cron_id) is not None

        ProviderRepo(pool).create(
            name=f"p_{uuid.uuid4().hex[:6]}",
            kind="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        assert len(ProviderRepo(pool).list_all()) >= 1
    finally:
        pool.close()


@requires_postgresql
@pytest.mark.postgresql
def test_pg_probe_ok() -> None:
    from octop.config import DatabaseConfig
    from octop.infra.db.probe import probe_database
    from octop.infra.utils.paths import PathLayout

    payload = _pg_payload_from_url(_conninfo())
    cfg = DatabaseConfig(
        driver="postgresql",
        url=str(payload["url"]),
        host=str(payload["host"]),
        port=int(payload["port"]),
        database=str(payload["database"]),
        user=str(payload["user"]),
        password=str(payload["password"]),
    )
    probe_database(cfg, PathLayout(Path("/tmp")))


@requires_postgresql
@pytest.mark.postgresql
def test_pg_backup_roundtrip(tmp_path: Path) -> None:
    if not shutil.which("pg_dump") or not shutil.which("pg_restore"):
        pytest.skip("pg_dump/pg_restore not on PATH")

    from octop.config import DatabaseConfig
    from octop.infra.backup.system_archive import create_system_backup, restore_system_backup
    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import PostgresPool
    from octop.infra.db.repos.users import UserRepo
    from octop.infra.utils.paths import PathLayout

    conninfo = _conninfo()
    payload = _pg_payload_from_url(conninfo)
    db_config = DatabaseConfig(
        driver="postgresql",
        url=conninfo,
        host=str(payload["host"]),
        port=int(payload["port"]),
        database=str(payload["database"]),
        user=str(payload["user"]),
        password=str(payload["password"]),
    )
    pool = PostgresPool(conninfo)
    try:
        _reset_public_schema(pool)
        run_migrations(pool)
        repo = UserRepo(pool)
        username = f"pg_bak_{uuid.uuid4().hex[:8]}"
        repo.create(username=username, password_hash="x", role="user")

        layout = PathLayout(tmp_path / ".octop")
        layout.root.mkdir(parents=True, exist_ok=True)
        layout.config.write_text('{"port": 8088}', encoding="utf-8")

        class Row:
            agent_id = "agent01"
            name = "Test"

        archive = tmp_path / "pg-backup.tar.gz"
        create_system_backup(
            paths=layout,
            agent_rows=[Row()],
            pool=pool,
            db_config=db_config,
            dest=archive,
        )

        _reset_public_schema(pool)
        run_migrations(pool)
        result = restore_system_backup(
            archive,
            paths=layout,
            pool=pool,
            db_config=db_config,
            restore_config=False,
        )
        assert result["database_driver"] == "postgresql"
        found = repo.get_by_username(username)
        assert found is not None
    finally:
        pool.close()


@requires_postgresql
@pytest.mark.postgresql
@pytest.mark.asyncio
async def test_setup_database_postgresql_bind(tmp_octop_home: Path) -> None:
    """Wizard: probe + bind live PostgreSQL, then create admin."""
    from octop.infra.db.pool import PostgresPool
    from octop.infra.setup.password_file import read_password
    from tests.support.app import octop_client

    pool = PostgresPool(_conninfo())
    try:
        _reset_public_schema(pool)
    finally:
        pool.close()

    payload = _pg_payload_from_url(_conninfo())
    async with octop_client(tmp_octop_home, bind_database=False) as (client, srv):
        assert srv.database_bound is False

        probed = await client.post("/api/setup/test-database", json=payload)
        assert probed.status_code == 200, probed.text
        assert probed.json()["ok"] is True

        bound = await client.post("/api/setup/database", json=payload)
        assert bound.status_code == 200, bound.text
        body = bound.json()
        assert body["ok"] is True
        assert body["driver"] == "postgresql"
        assert srv.database_bound is True

        status = await client.get("/api/setup/status")
        assert status.json()["database_bound"] is True
        assert status.json()["database_driver"] == "postgresql"

        pw = read_password(tmp_octop_home.parent)
        assert pw is not None
        verified = await client.post("/api/setup/verify-password", json={"password": pw})
        assert verified.status_code == 200, verified.text
        tok = verified.json()["wizard_token"]

        created = await client.post(
            "/api/setup/initial-admin",
            json={"username": "admin", "password": "AdminPass1", "display_name": "Admin"},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert created.status_code in (200, 201), created.text
        assert srv.user_manager is not None
        assert srv.user_manager.count() == 1


@requires_postgresql
@pytest.mark.postgresql
def test_pg_knowledge_base_max_documents_schema_and_crud() -> None:
    """Ensure PostgreSQL fresh migration includes max_documents on knowledge_bases and CRUD works."""
    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import PostgresPool
    from octop.infra.db.repos.knowledge import KnowledgeRepo
    from octop.infra.db.repos.users import UserRepo

    pool = PostgresPool(_conninfo())
    try:
        _reset_public_schema(pool)
        run_migrations(pool)

        # 1. Assert schema column exists in information_schema
        with pool.connect() as conn:
            cursor = conn.execute(
                """
                SELECT column_name, data_type, column_default
                FROM information_schema.columns
                WHERE table_name = 'knowledge_bases' AND column_name = 'max_documents';
                """
            )
            col = cursor.fetchone()
            assert col is not None, (
                "max_documents column missing from knowledge_bases in PostgreSQL"
            )
            assert col[1] == "integer"
            assert "100" in str(col[2])

        # 2. Assert repo can insert and retrieve knowledge base with default max_documents
        users = UserRepo(pool)
        uid = users.create(
            username=f"kb_user_{uuid.uuid4().hex[:8]}", password_hash="h", role="admin"
        )
        repo = KnowledgeRepo(pool)
        kb_default = repo.create_base(
            owner_user_id=uid,
            name="Default Limit Base",
        )
        assert kb_default.max_documents == 100

        # 3. Assert repo can insert with explicit max_documents
        kb_custom = repo.create_base(
            owner_user_id=uid,
            name="Custom Limit Base",
            max_documents=50,
        )
        assert kb_custom.max_documents == 50

        # 4. Assert update_base works with max_documents
        repo.update_base(kb_custom.id, max_documents=200)
        fetched = repo.get_base(kb_custom.id)
        assert fetched is not None
        assert fetched.max_documents == 200
    finally:
        pool.close()


@requires_postgresql
@pytest.mark.postgresql
def test_work_control_plane_revocation_and_restart_block_pending_execution() -> None:
    """Persisted membership, local runtime resources, and restart state fail closed."""
    from work_platform.authorization import (
        WorkAccessDenied,
        authorize_external,
        issue_execution_context,
    )
    from work_platform.runtime_adapter import RuntimeBinding
    from work_platform.runtime_handoff import issue_runtime_handoff, verify_runtime_handoff

    from octop.infra.db.pool import PostgresPool
    from octop.infra.work.control_plane import WorkControlPlane

    conninfo = _conninfo()
    setup = PostgresPool(conninfo)
    try:
        _reset_public_schema(setup)
    finally:
        setup.close()

    local_binding = RuntimeBinding(
        "org-a",
        "runtime-a",
        "octop_runtime_org_a",
        "org-a-data",
        "org-a-database-url",
        "https://runtime-a.internal:8088",
        "org-a-handoff",
    )
    control = WorkControlPlane(conninfo, "runtime-a", expected_runtime_binding=local_binding)
    try:
        with control._db.transaction() as conn:
            conn.execute(
                "INSERT INTO work_users(work_user_id, status) VALUES (?, 'active')", ("user-a",)
            )
            conn.execute(
                "INSERT INTO work_users(work_user_id, status) VALUES (?, 'active')", ("user-b",)
            )
            conn.execute(
                "INSERT INTO work_identities(runtime_id, octop_user_id, work_user_id, status) "
                "VALUES ('work-entry', 7, 'user-a', 'active'), "
                "('runtime-a', 41, 'user-a', 'active'), "
                "('runtime-b', 42, 'user-b', 'active')"
            )
            conn.execute(
                "INSERT INTO work_memberships(organization_id, work_user_id, role, status, revision) "
                "VALUES ('org-a', 'user-a', 'member', 'active', 1), "
                "('org-b', 'user-b', 'member', 'active', 1)"
            )
            conn.execute(
                "INSERT INTO work_organization_policies(organization_id, revision, available) "
                "VALUES ('org-a', 1, TRUE), ('org-b', 1, TRUE)"
            )
            conn.execute(
                "INSERT INTO work_agent_bindings(agent_id, organization_id, runtime_id, "
                "database_role, volume_id, secret_ref, endpoint, handoff_secret_ref, status) VALUES "
                "('agent-a', 'org-a', 'runtime-a', 'octop_runtime_org_a', 'org-a-data', "
                "'org-a-database-url', 'https://runtime-a.internal:8088', 'org-a-handoff', "
                "'active'), "
                "('agent-b', 'org-b', 'runtime-b', 'octop_runtime_org_b', 'org-b-data', "
                "'org-b-database-url', 'https://runtime-b.internal:8088', 'org-b-handoff', "
                "'active')"
            )
            conn.execute(
                "INSERT INTO work_capabilities(organization_id, capability, enabled, billable) "
                "VALUES ('org-a', 'model:local_stub', TRUE, TRUE)"
            )

        assert control.resolve_grant(41, "agent-a") is not None
        assert control.resolve_grant(41, "agent-b") is None
        assert control.resolve_runtime_grant("user-a", "agent-a") is not None
        entry = WorkControlPlane(conninfo, "work-entry")
        try:
            routed = entry.resolve_entry_grant(7, "agent-a")
            assert routed is not None and routed.runtime == local_binding
            assert entry.resolve_entry_grant(7, "agent-b") is None
        finally:
            entry.close()
        handoff_secret = b"org-a-handoff-secret-org-a-000000"
        handoff_token = issue_runtime_handoff(
            local_binding,
            work_user_id="user-a",
            agent_id="agent-a",
            connection_id="a" * 32,
            secret=handoff_secret,
        )
        handoff = verify_runtime_handoff(
            handoff_token,
            runtime_id="runtime-a",
            secret=handoff_secret,
        )
        with ProcessPoolExecutor(
            max_workers=2, mp_context=get_context("spawn"), max_tasks_per_child=1
        ) as executor:
            consumed = list(
                executor.map(_consume_handoff_process, [(conninfo, local_binding, handoff)] * 2)
            )
        assert len({pid for pid, _ in consumed}) == 2
        assert sum(accepted for _, accepted in consumed) == 1
        restarted_handoff = WorkControlPlane(
            conninfo, "runtime-a", expected_runtime_binding=local_binding
        )
        try:
            assert restarted_handoff.consume_runtime_handoff(handoff) is None
        finally:
            restarted_handoff.close()
        context, resolved = issue_execution_context(
            control,
            octop_user_id=41,
            agent_id="agent-a",
            run_id="run-a",
            budget_scope_id="thread-a",
            connection_id="a" * 32,
        )
        assert resolved == local_binding
        assert control.activate_run(context) is True
        assert control.reserve_attempt(context, "model:local_stub", "attempt-a") is True
        with ThreadPoolExecutor(max_workers=20) as executor:
            reserved = list(
                executor.map(
                    lambda attempt: control.reserve_attempt(context, "model:local_stub", attempt),
                    [f"attempt-race-{index}" for index in range(40)],
                )
            )
        assert sum(reserved) == 19
        with control._db.connect() as conn:
            counters = conn.execute(
                "SELECT scope_kind, used FROM work_budget_counters ORDER BY scope_kind"
            ).fetchall()
        assert {row["scope_kind"]: row["used"] for row in counters} == {
            "organization": 20,
            "task": 20,
            "user": 20,
        }

        # Task is the stable legacy thread, not a fresh allowance every UTC day.
        with control._db.transaction() as conn:
            conn.execute(
                "UPDATE work_budget_counters SET utc_day=utc_day - 1 WHERE scope_kind='task'"
            )
        assert control.reserve_attempt(context, "model:local_stub", "attempt-next-day") is False
        with control._db.connect() as conn:
            assert (
                conn.execute(
                    "SELECT attempt_id FROM work_external_attempts WHERE attempt_id='attempt-next-day'"
                ).fetchone()
                is None
            )

        with control._db.transaction() as conn:
            conn.execute(
                "UPDATE work_memberships SET status='removed', revision=2 "
                "WHERE organization_id='org-a' AND work_user_id='user-a'"
            )
        assert control.resolve_grant(41, "agent-a") is None
        assert control.resolve_runtime_grant("user-a", "agent-a") is None
        assert control.context_is_current(context) is False
    finally:
        control.close()

    restarted = WorkControlPlane(conninfo, "runtime-a", expected_runtime_binding=local_binding)
    try:
        with restarted._db.connect() as conn:
            run = conn.execute(
                "SELECT status, connection_id FROM work_runs WHERE run_id='run-a'"
            ).fetchone()
            attempt = conn.execute(
                "SELECT status FROM work_external_attempts WHERE attempt_id='attempt-a'"
            ).fetchone()
        assert run is not None and run["status"] == "blocked_restart"
        assert run["connection_id"] == "a" * 32
        assert attempt is not None and attempt["status"] == "uncertain"

        sent: list[str] = []
        with pytest.raises(WorkAccessDenied):
            authorize_external(
                context,
                "model:local_stub",
                restarted,
                attempt_id="attempt-after-restart",
                operation=lambda: sent.append("called"),
            )
        assert sent == []
        assert restarted.resolve_grant(41, "agent-a") is None
    finally:
        restarted.close()


@requires_postgresql
@pytest.mark.postgresql
def test_work_control_plane_v3_to_v5_migration_is_repeatable() -> None:
    from octop.infra.db.pool import PostgresPool
    from octop.infra.work.control_plane import WorkControlPlane

    conninfo = _conninfo()
    setup = PostgresPool(conninfo)
    try:
        _reset_public_schema(setup)
    finally:
        setup.close()

    fresh = WorkControlPlane(conninfo, "runtime-a")
    fresh.close()
    setup = PostgresPool(conninfo)
    try:
        with setup.transaction() as conn:
            conn.execute("DROP TABLE work_runtime_handoffs")
            conn.execute("ALTER TABLE work_runs DROP COLUMN connection_id")
            conn.execute("DELETE FROM work_schema_version")
            conn.execute("INSERT INTO work_schema_version(version) VALUES (3)")
    finally:
        setup.close()

    migrated = WorkControlPlane(conninfo, "runtime-a")
    migrated.close()
    repeated = WorkControlPlane(conninfo, "runtime-a")
    try:
        with repeated._db.connect() as conn:
            version = conn.execute(
                "SELECT MAX(version) AS version FROM work_schema_version"
            ).fetchone()
            table = conn.execute(
                "SELECT to_regclass('public.work_runtime_handoffs') AS table_name"
            ).fetchone()
            column = conn.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name='work_runs' AND column_name='connection_id'"
            ).fetchone()
        assert version is not None and version["version"] == 5
        assert table is not None and table["table_name"] == "work_runtime_handoffs"
        assert column is not None and column["is_nullable"] == "NO"
    finally:
        repeated.close()
