"""Offline, migration-owner-only historical import and per-object reconciliation.

Creates no Octop users, runtime bindings, executable tasks or active sessions.
This is the data-preservation phase; identity recovery and business activation
have separate gates. Production input files must never be committed to Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from work_platform.migration import MigrationError, digest, prepare_snapshot

_DDL = """
CREATE TABLE IF NOT EXISTS public.work_legacy_batches (
 source_digest TEXT PRIMARY KEY, source_counts JSONB NOT NULL, dispositions JSONB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('importing','imported_not_activated')));
CREATE TABLE IF NOT EXISTS public.work_legacy_records (
 source_table TEXT NOT NULL, source_id TEXT NOT NULL, source_digest TEXT NOT NULL,
 payload JSONB NOT NULL, payload_digest TEXT NOT NULL, PRIMARY KEY(source_table,source_id));
CREATE TABLE IF NOT EXISTS public.work_legacy_budget_attempts (
 scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL, utc_day DATE NOT NULL,
 attempt_hash TEXT NOT NULL,
 PRIMARY KEY(scope_kind,scope_id,utc_day,attempt_hash));
REVOKE ALL ON public.work_legacy_batches,public.work_legacy_records,
 public.work_legacy_budget_attempts FROM PUBLIC;
"""


def _copy_verified(objects: Path, destination: Path, files: list[dict[str, Any]]) -> None:
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in files:
        target = destination / item["sha256"]
        if target.exists():
            if target.is_symlink() or _file_digest(target) != item["sha256"]:
                raise MigrationError("existing immutable target object differs")
            continue
        # Verify the actual copied bytes, not just the earlier source preflight.
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                with (objects / item["object_key"]).open("rb") as source:
                    shutil.copyfileobj(source, temporary)
                temporary.flush()
                os.fsync(temporary.fileno())
                if (
                    _file_digest(temporary_path) != item["sha256"]
                    or temporary_path.stat().st_size != item["size_bytes"]
                ):
                    raise MigrationError("copied object integrity mismatch")
                os.replace(temporary_path, target)
            finally:
                temporary_path.unlink(missing_ok=True)


def _file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def import_snapshot(
    url: str,
    tables: dict[str, list[dict[str, Any]]],
    objects: Path,
    object_hashes: dict[str, str],
    destination: Path,
    *,
    stop_after: int | None = None,
) -> dict[str, Any]:
    projection = prepare_snapshot(tables, objects, object_hashes)
    source_digest = projection["source_digest"]
    with psycopg.connect(url, autocommit=True) as db:
        # One offline importer; this does not serialize business execution.
        db.execute("SELECT pg_advisory_lock(hashtextextended('work-legacy-import',0))")
        db.execute(_DDL)
        existing = db.execute(
            "SELECT source_digest FROM work_legacy_batches WHERE source_digest<>%s",
            (source_digest,),
        ).fetchone()
        if existing:
            raise MigrationError(
                "different source snapshot requires an explicit incremental migration"
            )
        db.execute(
            "INSERT INTO work_legacy_batches VALUES(%s,%s,%s,'importing') ON CONFLICT DO NOTHING",
            (source_digest, Jsonb(projection["source_counts"]), Jsonb(projection["dispositions"])),
        )
        _copy_verified(objects, destination, projection["files"])
        count = 0
        # ponytail: per-record durable checkpoint; batch only if measured import time requires it.
        for table, rows in projection["records"].items():
            for row in rows:
                field = {
                    "workAiCallBudgets": "scopeId",
                    "accountSecurityRateLimits": "subjectHash",
                }.get(table, "id")
                sid = str(row[field])
                previous = db.execute(
                    "SELECT payload_digest,source_digest,payload FROM work_legacy_records "
                    "WHERE source_table=%s AND source_id=%s",
                    (table, sid),
                ).fetchone()
                if previous is not None and (
                    previous[:2] != (digest(row), source_digest) or previous[2] != row
                ):
                    raise MigrationError("existing source mapping differs; no overwrite performed")
                db.execute(
                    "INSERT INTO work_legacy_records VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (table, sid, source_digest, Jsonb(row), digest(row)),
                )
                count += 1
                if stop_after is not None and count >= stop_after:
                    raise InterruptedError(
                        "explicit rehearsal interruption after durable checkpoint"
                    )
        with db.transaction():
            for row in tables["users"]:
                inserted = db.execute(
                    "INSERT INTO work_users VALUES(%s,'active') "
                    "ON CONFLICT(work_user_id) DO UPDATE SET status=work_users.status "
                    "WHERE work_users.status=EXCLUDED.status RETURNING work_user_id",
                    ("legacy:" + str(row["id"]),),
                ).fetchone()
                if inserted is None:
                    raise MigrationError("existing authority differs: user")
            for membership in projection["memberships"]:
                inserted = db.execute(
                    "INSERT INTO work_memberships VALUES(%s,%s,%s,%s,%s) "
                    "ON CONFLICT(organization_id,work_user_id) DO UPDATE SET "
                    "revision=work_memberships.revision WHERE "
                    "(work_memberships.role,work_memberships.status,work_memberships.revision)="
                    "(EXCLUDED.role,EXCLUDED.status,EXCLUDED.revision) RETURNING work_user_id",
                    membership,
                ).fetchone()
                if inserted is None:
                    raise MigrationError("existing authority differs: membership")
            for budget in projection["budgets"]:
                inserted = db.execute(
                    "INSERT INTO work_budget_counters VALUES(%s,%s,%s,%s) "
                    "ON CONFLICT(scope_kind,scope_id,utc_day) DO UPDATE SET "
                    "used=work_budget_counters.used WHERE work_budget_counters.used=EXCLUDED.used "
                    "RETURNING scope_id",
                    budget,
                ).fetchone()
                if inserted is None:
                    raise MigrationError("existing authority differs: quota")
            for attempt in projection["budget_attempts"]:
                db.execute(
                    "INSERT INTO work_legacy_budget_attempts VALUES(%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    attempt,
                )
            db.execute(
                "UPDATE work_legacy_batches SET state='imported_not_activated' "
                "WHERE source_digest=%s",
                (source_digest,),
            )
    return {
        "source_digest": source_digest,
        "state": "IMPORTED_NOT_ACTIVATED",
        "identity_mapping": "NOT_RUN",
        "business_activation": "NOT_RUN",
        "source_counts": projection["source_counts"],
        "copied_files": len(projection["files"]),
    }


def reconcile_snapshot(
    url: str,
    tables: dict[str, list[dict[str, Any]]],
    objects: Path,
    object_hashes: dict[str, str],
    destination: Path,
) -> dict[str, Any]:
    projection = prepare_snapshot(tables, objects, object_hashes)
    failures = []
    with psycopg.connect(url) as db:
        actual = {
            (table, sid): payload
            for table, sid, payload in db.execute(
                "SELECT source_table,source_id,payload FROM work_legacy_records "
                "WHERE source_digest=%s",
                (projection["source_digest"],),
            )
        }
        expected = {}
        for table, rows in projection["records"].items():
            for row in rows:
                field = {
                    "workAiCallBudgets": "scopeId",
                    "accountSecurityRateLimits": "subjectHash",
                }.get(table, "id")
                expected[(table, str(row[field]))] = row
        if actual != expected:
            failures.append("record_count_relationship_state_or_payload")
        for row in tables["users"]:
            if db.execute(
                "SELECT status FROM work_users WHERE work_user_id=%s",
                ("legacy:" + str(row["id"]),),
            ).fetchone() != ("active",):
                failures.append("user")
        for org, user, role, status, revision in projection["memberships"]:
            if db.execute(
                "SELECT role,status,revision FROM work_memberships "
                "WHERE organization_id=%s AND work_user_id=%s",
                (org, user),
            ).fetchone() != (role, status, revision):
                failures.append("membership")
        for kind, sid, day, used in projection["budgets"]:
            result = db.execute(
                "SELECT used FROM work_budget_counters "
                "WHERE scope_kind=%s AND scope_id=%s AND utc_day=%s",
                (kind, sid, day),
            ).fetchone()
            if result != (used,):
                failures.append("quota")
        for kind, sid, day, key in projection["budget_attempts"]:
            if not db.execute(
                "SELECT 1 FROM work_legacy_budget_attempts "
                "WHERE scope_kind=%s AND scope_id=%s AND utc_day=%s AND attempt_hash=%s",
                (kind, sid, day, key),
            ).fetchone():
                failures.append("quota_attempt")
    for item in projection["files"]:
        target = destination / item["sha256"]
        if not target.is_file() or target.is_symlink() or _file_digest(target) != item["sha256"]:
            failures.append("target_file")
    return {
        "source_digest": projection["source_digest"],
        "integrity": "FAIL" if failures else "PASS",
        "failures": sorted(set(failures)),
        "business_activation": "NOT_RUN",
        "identity_mapping": "NOT_RUN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("import", "reconcile"))
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--objects", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.snapshot.read_text())
    operation = import_snapshot if args.command == "import" else reconcile_snapshot
    result = operation(
        os.environ["WORK_MIGRATION_DATABASE_URL"],
        payload["tables"],
        args.objects,
        payload["object_hashes"],
        args.destination,
    )
    print(json.dumps(result, ensure_ascii=False))
    return int(result.get("integrity") == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
