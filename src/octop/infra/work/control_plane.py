"""PostgreSQL-backed Work identity, execution and budget records.

This database is separate from Octop's control/runtime database. It is opened
only when WORK_CONTROL_DATABASE_URL is configured; without it, Work task
execution remains unavailable and the Octop server can still start.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from work_platform.authorization import ExecutionGrant
from work_platform.capability_policy import CapabilityPolicy
from work_platform.runtime_adapter import RuntimeBinding
from work_platform.runtime_context import ExecutionContext
from work_platform.runtime_handoff import RuntimeHandoff

from octop.infra.db.pool import PostgresPool

_MIGRATION = 7
_MIGRATION_LOCK = 6738912460123
logger = logging.getLogger(__name__)


class _BudgetLimitReached(Exception):
    pass


def _read(row: Any, name: str) -> Any:
    if row is None:
        return None
    try:
        return row[name]
    except (KeyError, TypeError):
        return getattr(row, name, None)


class WorkControlPlane:
    """Work's persistent identity and dispatch boundary for one Octop runtime."""

    def __init__(
        self,
        database_url: str,
        runtime_id: str,
        *,
        expected_runtime_binding: RuntimeBinding | None = None,
    ) -> None:
        if not database_url.strip():
            raise ValueError("Work control database URL is required")
        if not runtime_id.strip():
            raise ValueError("Work runtime ID is required")
        self.runtime_id = runtime_id.strip()
        if (
            expected_runtime_binding is not None
            and expected_runtime_binding.runtime_id != self.runtime_id
        ):
            raise ValueError("local runtime binding does not match Work runtime ID")
        self.expected_runtime_binding = expected_runtime_binding
        self._db = PostgresPool(database_url, min_size=1, max_size=4)
        self._executor_id = uuid.uuid4().hex
        self._executor: Any = None
        try:
            self._migrate()
            with self._db.connect() as conn:
                owner = conn.execute(
                    "SELECT pg_has_role(session_user, relowner, 'USAGE') AS trusted "
                    "FROM pg_class WHERE oid='public.work_runs'::regclass"
                ).fetchone()
            self._secured = not bool(_read(owner, "trusted"))
            import psycopg

            # Never return a session lock to a connection pool or silently reconnect it.
            self._executor = psycopg.connect(database_url, autocommit=True, connect_timeout=5)
            if self._secured:
                self._executor.execute(
                    "SELECT public.work_register_executor(%s,%s)",
                    (self._executor_id, self.runtime_id),
                )
            else:
                self._executor.execute(
                    "SELECT pg_advisory_lock(hashtextextended(%s, 0))", (self._executor_id,)
                )
            self._block_incomplete_runs()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._executor is not None:
            self._executor.close()
        self._db.close()

    def _migrate(self) -> None:
        with self._db.transaction() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(?)", (_MIGRATION_LOCK,))
            # Current runtimes need DML only; schema creation belongs to the migration role.
            exists = conn.execute("SELECT to_regclass('work_schema_version') AS name").fetchone()
            if _read(exists, "name") is None:
                conn.execute(
                    "CREATE TABLE work_schema_version "
                    "(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM work_schema_version"
            ).fetchone()
            version = int(_read(row, "version") or 0)
            if version > _MIGRATION:
                raise RuntimeError("Work control schema is newer than this application")
            if version == _MIGRATION:
                return
            if version == 1:
                conn.execute(
                    "CREATE TABLE work_users (work_user_id TEXT PRIMARY KEY, "
                    "status TEXT NOT NULL CHECK (status IN ('active','disabled')))",
                )
                conn.execute(
                    "INSERT INTO work_users(work_user_id, status) "
                    "SELECT work_user_id, status FROM work_identities"
                )
                conn.execute(
                    "ALTER TABLE work_memberships DROP CONSTRAINT IF EXISTS "
                    "work_memberships_work_user_id_fkey"
                )
                conn.execute("ALTER TABLE work_identities RENAME TO work_identities_v1")
                conn.execute(
                    "CREATE TABLE work_identities ("
                    "runtime_id TEXT NOT NULL, octop_user_id BIGINT NOT NULL, "
                    "work_user_id TEXT NOT NULL REFERENCES work_users(work_user_id), "
                    "status TEXT NOT NULL CHECK (status IN ('active','disabled')), "
                    "PRIMARY KEY (runtime_id, octop_user_id))"
                )
                conn.execute(
                    "INSERT INTO work_identities(runtime_id, octop_user_id, work_user_id, status) "
                    "SELECT 'unmapped', octop_user_id, work_user_id, 'disabled' "
                    "FROM work_identities_v1"
                )
                conn.execute(
                    "ALTER TABLE work_memberships ADD CONSTRAINT "
                    "work_memberships_work_user_id_fkey FOREIGN KEY (work_user_id) "
                    "REFERENCES work_users(work_user_id)"
                )
                conn.execute("DROP TABLE work_identities_v1")
                conn.execute(
                    "INSERT INTO work_schema_version(version) VALUES (?)",
                    (2,),
                )
                version = 2

            if version == 2:
                conn.execute("ALTER TABLE work_agent_bindings ADD COLUMN endpoint TEXT")
                conn.execute("ALTER TABLE work_agent_bindings ADD COLUMN handoff_secret_ref TEXT")
                conn.execute("INSERT INTO work_schema_version(version) VALUES (?)", (3,))
                version = 3

            if version == 3:
                conn.execute(
                    "CREATE TABLE work_runtime_handoffs ("
                    "handoff_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, "
                    "runtime_id TEXT NOT NULL, "
                    "work_user_id TEXT NOT NULL, organization_id TEXT NOT NULL, "
                    "agent_id TEXT NOT NULL, issued_at TIMESTAMPTZ NOT NULL, "
                    "expires_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                conn.execute("INSERT INTO work_schema_version(version) VALUES (?)", (4,))
                version = 4

            if version == 4:
                conn.execute("ALTER TABLE work_runs ADD COLUMN connection_id TEXT")
                conn.execute(
                    "UPDATE work_runs SET connection_id=run_id WHERE connection_id IS NULL"
                )
                conn.execute("ALTER TABLE work_runs ALTER COLUMN connection_id SET NOT NULL")
                conn.execute("INSERT INTO work_schema_version(version) VALUES (?)", (5,))
                version = 5

            if version == 5:
                conn.execute("ALTER TABLE work_runs ADD COLUMN executor_id TEXT")
                conn.execute("INSERT INTO work_schema_version(version) VALUES (?)", (6,))
                version = 6

            if version == 6:
                conn.execute(Path(__file__).with_name("runtime_permissions.sql").read_text())
                conn.execute("INSERT INTO work_schema_version(version) VALUES (?)", (_MIGRATION,))
                return

            statements = (
                """CREATE TABLE work_users (
                    work_user_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK (status IN ('active','disabled'))
                )""",
                """CREATE TABLE work_identities (
                    runtime_id TEXT NOT NULL,
                    octop_user_id BIGINT NOT NULL,
                    work_user_id TEXT NOT NULL REFERENCES work_users(work_user_id),
                    status TEXT NOT NULL CHECK (status IN ('active','disabled')),
                    PRIMARY KEY (runtime_id, octop_user_id)
                )""",
                """CREATE TABLE work_memberships (
                    organization_id TEXT NOT NULL,
                    work_user_id TEXT NOT NULL REFERENCES work_users(work_user_id),
                    role TEXT NOT NULL CHECK (role IN ('member','manager','owner')),
                    status TEXT NOT NULL CHECK (status IN ('active','suspended','removed')),
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    PRIMARY KEY (organization_id, work_user_id)
                )""",
                """CREATE TABLE work_agent_bindings (
                    agent_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    database_role TEXT NOT NULL,
                    volume_id TEXT NOT NULL,
                    secret_ref TEXT NOT NULL,
                    endpoint TEXT,
                    handoff_secret_ref TEXT,
                    status TEXT NOT NULL CHECK (status IN ('active','disabled'))
                )""",
                """CREATE TABLE work_organization_policies (
                    organization_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    available BOOLEAN NOT NULL DEFAULT TRUE
                )""",
                """CREATE TABLE work_capabilities (
                    organization_id TEXT NOT NULL REFERENCES work_organization_policies(organization_id),
                    capability TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    billable BOOLEAN NOT NULL DEFAULT FALSE,
                    PRIMARY KEY (organization_id, capability)
                )""",
                """CREATE TABLE work_runs (
                    run_id TEXT PRIMARY KEY,
                    octop_user_id BIGINT NOT NULL,
                    work_user_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    executor_id TEXT,
                    membership_revision INTEGER NOT NULL,
                    policy_revision INTEGER NOT NULL,
                    issued_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL CHECK (status IN
                        ('queued','running','completed','failed','blocked','blocked_restart')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    finished_at TIMESTAMPTZ
                )""",
                """CREATE TABLE work_budget_counters (
                    scope_kind TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    utc_day DATE NOT NULL,
                    used INTEGER NOT NULL CHECK (used >= 0),
                    PRIMARY KEY (scope_kind, scope_id, utc_day)
                )""",
                """CREATE TABLE work_external_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES work_runs(run_id),
                    budget_scope_id TEXT NOT NULL,
                    work_user_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    utc_day DATE NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('reserved','completed','uncertain')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    finished_at TIMESTAMPTZ
                )""",
                "CREATE INDEX work_attempt_budget_scope ON work_external_attempts "
                "(budget_scope_id, work_user_id, organization_id, utc_day)",
                """CREATE TABLE work_runtime_handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    connection_id TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,
                    work_user_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    issued_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    consumed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )""",
            )
            for statement in statements:
                conn.execute(statement)
            conn.execute(Path(__file__).with_name("runtime_permissions.sql").read_text())
            conn.execute("INSERT INTO work_schema_version(version) VALUES (?)", (_MIGRATION,))

    def _block_incomplete_runs(self) -> None:
        if self._secured:
            self._secure_call("work_recover_runs", self.runtime_id)
            return
        with self._db.transaction() as conn:
            owners = conn.execute(
                "SELECT DISTINCT executor_id FROM work_runs r "
                "WHERE runtime_id=? AND (status IN ('queued','running') OR EXISTS "
                "(SELECT 1 FROM work_external_attempts a "
                "WHERE a.run_id=r.run_id AND a.status='reserved'))",
                (self.runtime_id,),
            ).fetchall()
            for owner in owners:
                executor_id = _read(owner, "executor_id")
                if executor_id is not None:
                    acquired = conn.execute(
                        "SELECT pg_try_advisory_xact_lock(hashtextextended(?, 0)) AS acquired",
                        (executor_id,),
                    ).fetchone()
                    if not bool(_read(acquired, "acquired")):
                        continue
                # Missing v5 ownership is conservatively interrupted, never re-executed.
                conn.execute(
                    "UPDATE work_runs SET status='blocked_restart', finished_at=now() "
                    "WHERE runtime_id=? AND executor_id IS NOT DISTINCT FROM ? "
                    "AND status IN ('queued','running')",
                    (self.runtime_id, executor_id),
                )
                conn.execute(
                    "UPDATE work_external_attempts e SET status='uncertain', finished_at=now() "
                    "FROM work_runs r WHERE e.run_id=r.run_id AND r.runtime_id=? "
                    "AND r.executor_id IS NOT DISTINCT FROM ? "
                    "AND e.status='reserved'",
                    (self.runtime_id, executor_id),
                )

    def _executor_is_live(self) -> bool:
        import psycopg

        try:
            if self._executor is None or self._executor.closed:
                return False
            self._executor.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False

    def _secure_call(self, name: str, *args: Any) -> Any:
        with self._db.transaction() as conn:
            placeholders = ",".join("?" for _ in args)
            row = conn.execute(f"SELECT public.{name}({placeholders}) AS value", args).fetchone()
            return _read(row, "value")

    @staticmethod
    def _json_payload(value: Any) -> Any:
        from psycopg.types.json import Jsonb

        payload = json.loads(
            json.dumps(
                asdict(value),
                default=lambda v: v.isoformat() if isinstance(v, datetime) else sorted(v),
            )
        )
        return Jsonb(payload)

    def resolve_grant(self, octop_user_id: int, agent_id: str) -> ExecutionGrant | None:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT i.octop_user_id, i.work_user_id, m.organization_id, "
                "m.status AS member_status, m.revision AS membership_revision, "
                "p.revision AS policy_revision, a.agent_id, a.runtime_id, a.database_role, "
                "a.volume_id, a.secret_ref, a.endpoint, a.handoff_secret_ref "
                "FROM work_identities i "
                "JOIN work_users u ON u.work_user_id=i.work_user_id AND u.status='active' "
                "JOIN work_memberships m ON m.work_user_id=i.work_user_id "
                "JOIN work_agent_bindings a ON a.organization_id=m.organization_id "
                "JOIN work_organization_policies p ON p.organization_id=m.organization_id "
                "WHERE i.runtime_id=? AND i.octop_user_id=? AND i.status='active' "
                "AND m.status='active' "
                "AND a.agent_id=? AND a.runtime_id=? AND a.status='active' AND p.available=TRUE",
                (self.runtime_id, octop_user_id, agent_id, self.runtime_id),
            ).fetchall()
        if len(rows) != 1:
            return None
        row = rows[0]
        runtime = RuntimeBinding(
            organization_id=str(_read(row, "organization_id")),
            runtime_id=str(_read(row, "runtime_id")),
            database_role=str(_read(row, "database_role")),
            volume_id=str(_read(row, "volume_id")),
            secret_ref=str(_read(row, "secret_ref")),
            endpoint=_read(row, "endpoint"),
            handoff_secret_ref=_read(row, "handoff_secret_ref"),
        )
        if self.expected_runtime_binding is None or runtime != self.expected_runtime_binding:
            return None
        return ExecutionGrant(
            octop_user_id=int(_read(row, "octop_user_id")),
            work_user_id=str(_read(row, "work_user_id")),
            organization_id=str(_read(row, "organization_id")),
            agent_id=str(_read(row, "agent_id")),
            member_status=str(_read(row, "member_status")),
            membership_revision=int(_read(row, "membership_revision")),
            policy_revision=int(_read(row, "policy_revision")),
            runtime=runtime,
        )

    def resolve_entry_grant(self, octop_user_id: int, agent_id: str) -> ExecutionGrant | None:
        """Resolve a front-door login to its server-selected remote runtime."""
        if self.expected_runtime_binding is not None:
            return None
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT i.octop_user_id, i.work_user_id, m.organization_id, "
                "m.status AS member_status, m.revision AS membership_revision, "
                "p.revision AS policy_revision, a.agent_id, a.runtime_id, a.database_role, "
                "a.volume_id, a.secret_ref, a.endpoint, a.handoff_secret_ref "
                "FROM work_identities i "
                "JOIN work_users u ON u.work_user_id=i.work_user_id AND u.status='active' "
                "JOIN work_memberships m ON m.work_user_id=i.work_user_id "
                "JOIN work_agent_bindings a ON a.organization_id=m.organization_id "
                "JOIN work_organization_policies p ON p.organization_id=m.organization_id "
                "WHERE i.runtime_id=? AND i.octop_user_id=? AND i.status='active' "
                "AND m.status='active' AND a.agent_id=? AND a.status='active' "
                "AND p.available=TRUE",
                (self.runtime_id, octop_user_id, agent_id),
            ).fetchall()
        if len(rows) != 1:
            return None
        row = rows[0]
        runtime = RuntimeBinding(
            organization_id=str(_read(row, "organization_id")),
            runtime_id=str(_read(row, "runtime_id")),
            database_role=str(_read(row, "database_role")),
            volume_id=str(_read(row, "volume_id")),
            secret_ref=str(_read(row, "secret_ref")),
            endpoint=_read(row, "endpoint"),
            handoff_secret_ref=_read(row, "handoff_secret_ref"),
        )
        try:
            runtime.require_handoff()
        except LookupError:
            return None
        return ExecutionGrant(
            octop_user_id=int(_read(row, "octop_user_id")),
            work_user_id=str(_read(row, "work_user_id")),
            organization_id=str(_read(row, "organization_id")),
            agent_id=str(_read(row, "agent_id")),
            member_status=str(_read(row, "member_status")),
            membership_revision=int(_read(row, "membership_revision")),
            policy_revision=int(_read(row, "policy_revision")),
            runtime=runtime,
        )

    def resolve_runtime_grant(self, work_user_id: str, agent_id: str) -> ExecutionGrant | None:
        """Resolve a trusted global Work identity to this runtime's local user."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT i.octop_user_id, i.work_user_id, m.organization_id, "
                "m.status AS member_status, m.revision AS membership_revision, "
                "p.revision AS policy_revision, a.agent_id, a.runtime_id, a.database_role, "
                "a.volume_id, a.secret_ref, a.endpoint, a.handoff_secret_ref "
                "FROM work_identities i "
                "JOIN work_users u ON u.work_user_id=i.work_user_id AND u.status='active' "
                "JOIN work_memberships m ON m.work_user_id=i.work_user_id "
                "JOIN work_agent_bindings a ON a.organization_id=m.organization_id "
                "JOIN work_organization_policies p ON p.organization_id=m.organization_id "
                "WHERE i.runtime_id=? AND i.work_user_id=? AND i.status='active' "
                "AND m.status='active' AND a.agent_id=? AND a.runtime_id=? "
                "AND a.status='active' AND p.available=TRUE",
                (self.runtime_id, work_user_id, agent_id, self.runtime_id),
            ).fetchall()
        if len(rows) != 1:
            return None
        row = rows[0]
        runtime = RuntimeBinding(
            organization_id=str(_read(row, "organization_id")),
            runtime_id=str(_read(row, "runtime_id")),
            database_role=str(_read(row, "database_role")),
            volume_id=str(_read(row, "volume_id")),
            secret_ref=str(_read(row, "secret_ref")),
            endpoint=_read(row, "endpoint"),
            handoff_secret_ref=_read(row, "handoff_secret_ref"),
        )
        if self.expected_runtime_binding is None or runtime != self.expected_runtime_binding:
            return None
        return ExecutionGrant(
            octop_user_id=int(_read(row, "octop_user_id")),
            work_user_id=str(_read(row, "work_user_id")),
            organization_id=str(_read(row, "organization_id")),
            agent_id=str(_read(row, "agent_id")),
            member_status=str(_read(row, "member_status")),
            membership_revision=int(_read(row, "membership_revision")),
            policy_revision=int(_read(row, "policy_revision")),
            runtime=runtime,
        )

    def consume_runtime_handoff(self, handoff: RuntimeHandoff) -> ExecutionGrant | None:
        """Atomically re-authorize and consume one target-runtime handoff."""
        if handoff.runtime_id != self.runtime_id or self.expected_runtime_binding is None:
            return None
        if self._secured:
            row = self._secure_call("work_consume_handoff", self._json_payload(handoff))
            if row is None:
                return None
            return self.resolve_runtime_grant(handoff.work_user_id, handoff.agent_id)
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT i.octop_user_id, i.work_user_id, m.organization_id, "
                "m.status AS member_status, m.revision AS membership_revision, "
                "p.revision AS policy_revision, a.agent_id, a.runtime_id, a.database_role, "
                "a.volume_id, a.secret_ref, a.endpoint, a.handoff_secret_ref "
                "FROM work_identities i "
                "JOIN work_users u ON u.work_user_id=i.work_user_id AND u.status='active' "
                "JOIN work_memberships m ON m.work_user_id=i.work_user_id "
                "JOIN work_agent_bindings a ON a.organization_id=m.organization_id "
                "JOIN work_organization_policies p ON p.organization_id=m.organization_id "
                "WHERE i.runtime_id=? AND i.work_user_id=? AND i.status='active' "
                "AND m.organization_id=? AND m.status='active' "
                "AND a.agent_id=? AND a.runtime_id=? AND a.status='active' "
                "AND p.available=TRUE FOR SHARE OF i, u, m, a, p",
                (
                    self.runtime_id,
                    handoff.work_user_id,
                    handoff.organization_id,
                    handoff.agent_id,
                    self.runtime_id,
                ),
            ).fetchall()
            if len(rows) != 1:
                return None
            row = rows[0]
            runtime = RuntimeBinding(
                organization_id=str(_read(row, "organization_id")),
                runtime_id=str(_read(row, "runtime_id")),
                database_role=str(_read(row, "database_role")),
                volume_id=str(_read(row, "volume_id")),
                secret_ref=str(_read(row, "secret_ref")),
                endpoint=_read(row, "endpoint"),
                handoff_secret_ref=_read(row, "handoff_secret_ref"),
            )
            if runtime != self.expected_runtime_binding:
                return None
            inserted = conn.execute(
                "INSERT INTO work_runtime_handoffs("
                "handoff_id, connection_id, runtime_id, work_user_id, organization_id, agent_id, "
                "issued_at, expires_at) SELECT ?, ?, ?, ?, ?, ?, ?, ? WHERE ? > now() "
                "ON CONFLICT(handoff_id) DO NOTHING RETURNING handoff_id",
                (
                    handoff.handoff_id,
                    handoff.connection_id,
                    handoff.runtime_id,
                    handoff.work_user_id,
                    handoff.organization_id,
                    handoff.agent_id,
                    handoff.issued_at,
                    handoff.expires_at,
                    handoff.expires_at,
                ),
            ).fetchone()
            if inserted is None:
                return None
            logger.info(
                "work_runtime_handoff_consumed",
                extra={
                    "work_connection_id": handoff.connection_id,
                    "work_handoff_id": handoff.handoff_id,
                    "work_runtime_id": handoff.runtime_id,
                    "work_organization_id": handoff.organization_id,
                    "work_agent_id": handoff.agent_id,
                },
            )
            return ExecutionGrant(
                octop_user_id=int(_read(row, "octop_user_id")),
                work_user_id=str(_read(row, "work_user_id")),
                organization_id=str(_read(row, "organization_id")),
                agent_id=str(_read(row, "agent_id")),
                member_status=str(_read(row, "member_status")),
                membership_revision=int(_read(row, "membership_revision")),
                policy_revision=int(_read(row, "policy_revision")),
                runtime=runtime,
            )

    def create_run(self, context: ExecutionContext) -> None:
        if (
            context.octop_user_id is None
            or context.agent_id is None
            or context.runtime_id is None
            or context.connection_id is None
            or context.runtime_id != self.runtime_id
            or not self._executor_is_live()
        ):
            raise ValueError("Work execution context is incomplete")
        if self._secured:
            self._secure_call("work_create_run", self._json_payload(context), self._executor_id)
            return
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO work_runs(run_id, octop_user_id, work_user_id, organization_id, "
                "agent_id, runtime_id, thread_id, connection_id, membership_revision, "
                "policy_revision, issued_at, expires_at, executor_id, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued')",
                (
                    context.run_id,
                    context.octop_user_id,
                    context.work_user_id,
                    context.organization_id,
                    context.agent_id,
                    context.runtime_id,
                    context.budget_scope_id,
                    context.connection_id,
                    context.membership_revision,
                    context.policy_revision,
                    context.issued_at,
                    context.expires_at,
                    self._executor_id,
                ),
            )
        logger.info(
            "work_run_created",
            extra={
                "work_connection_id": context.connection_id,
                "work_run_id": context.run_id,
                "work_runtime_id": context.runtime_id,
                "work_organization_id": context.organization_id,
                "work_agent_id": context.agent_id,
            },
        )

    def activate_run(self, context: ExecutionContext) -> bool:
        if self._secured:
            return bool(
                self._secure_call(
                    "work_run_transition", self._json_payload(context), self._executor_id, "running"
                )
            )
        with self._db.transaction() as conn:
            if not self._context_matches(conn, context, statuses=("queued",)):
                return False
            cursor = conn.execute(
                "UPDATE work_runs SET status='running' WHERE run_id=? "
                "AND executor_id=? AND status='queued'",
                (context.run_id, self._executor_id),
            )
            return bool(cursor.rowcount == 1)

    def finish_run(self, context: ExecutionContext, status: str) -> None:
        if status not in {"completed", "failed", "blocked"}:
            raise ValueError("invalid Work run terminal status")
        if not self._executor_is_live():
            return
        if self._secured:
            self._secure_call(
                "work_run_transition", self._json_payload(context), self._executor_id, status
            )
            return
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE work_runs SET status=?, finished_at=now() "
                "WHERE run_id=? AND runtime_id=? AND executor_id=? AND status='running'",
                (status, context.run_id, self.runtime_id, self._executor_id),
            )

    def block_run(self, context: ExecutionContext) -> None:
        if not self._executor_is_live():
            return
        if self._secured:
            self._secure_call(
                "work_run_transition", self._json_payload(context), self._executor_id, "blocked"
            )
            return
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE work_runs SET status='blocked', finished_at=now() "
                "WHERE run_id=? AND runtime_id=? AND executor_id=? "
                "AND status IN ('queued','running')",
                (context.run_id, self.runtime_id, self._executor_id),
            )

    def context_is_current(self, context: ExecutionContext) -> bool:
        with self._db.connect() as conn:
            return self._context_matches(conn, context, statuses=("running",))

    def _context_matches(
        self,
        conn: Any,
        context: ExecutionContext,
        *,
        statuses: tuple[str, ...],
    ) -> bool:
        binding = self.expected_runtime_binding
        if (
            binding is None
            or context.octop_user_id is None
            or context.agent_id is None
            or context.runtime_id != self.runtime_id
            or not self._executor_is_live()
        ):
            return False
        status_values = statuses + (statuses[-1],) * (3 - len(statuses))
        row = conn.execute(
            "SELECT 1 FROM work_runs r "
            "JOIN work_identities i ON i.runtime_id=r.runtime_id "
            "AND i.octop_user_id=r.octop_user_id AND i.work_user_id=r.work_user_id "
            "AND i.status='active' "
            "JOIN work_users u ON u.work_user_id=r.work_user_id AND u.status='active' "
            "JOIN work_memberships m ON m.work_user_id=r.work_user_id "
            "AND m.organization_id=r.organization_id AND m.status='active' "
            "JOIN work_agent_bindings a ON a.agent_id=r.agent_id "
            "AND a.organization_id=r.organization_id AND a.runtime_id=r.runtime_id "
            "AND a.status='active' AND a.database_role=? AND a.volume_id=? AND a.secret_ref=? "
            "JOIN work_organization_policies p ON p.organization_id=r.organization_id "
            "AND p.available=TRUE "
            "WHERE r.run_id=? AND r.octop_user_id=? AND r.work_user_id=? "
            "AND r.organization_id=? AND r.agent_id=? AND r.runtime_id=? AND r.thread_id=? "
            "AND r.membership_revision=? AND m.revision=r.membership_revision "
            "AND r.policy_revision=? AND p.revision=r.policy_revision "
            "AND r.executor_id=? "
            "AND r.issued_at<=now() AND r.expires_at>now() AND r.status IN (?,?,?)",
            (
                binding.database_role,
                binding.volume_id,
                binding.secret_ref,
                context.run_id,
                context.octop_user_id,
                context.work_user_id,
                context.organization_id,
                context.agent_id,
                context.runtime_id,
                context.budget_scope_id,
                context.membership_revision,
                context.policy_revision,
                self._executor_id,
                *status_values,
            ),
        ).fetchone()
        return row is not None

    def load_policy(self, context: ExecutionContext) -> CapabilityPolicy | None:
        with self._db.connect() as conn:
            org = conn.execute(
                "SELECT revision, available FROM work_organization_policies "
                "WHERE organization_id=?",
                (context.organization_id,),
            ).fetchone()
            if org is None or not bool(_read(org, "available")):
                return None
            if int(_read(org, "revision")) != context.policy_revision:
                return None
            rows = conn.execute(
                "SELECT capability, billable FROM work_capabilities "
                "WHERE organization_id=? AND enabled=TRUE",
                (context.organization_id,),
            ).fetchall()
        enabled = frozenset(str(_read(row, "capability")) for row in rows)
        billable = frozenset(
            str(_read(row, "capability")) for row in rows if bool(_read(row, "billable"))
        )
        return CapabilityPolicy(enabled=enabled, billable=billable)

    def reserve_attempt(self, context: ExecutionContext, capability: str, attempt_id: str) -> bool:
        if context.agent_id is None or context.runtime_id != self.runtime_id:
            return False
        if self._secured:
            return bool(
                self._secure_call(
                    "work_reserve_attempt",
                    self._json_payload(context),
                    self._executor_id,
                    capability,
                    attempt_id,
                )
            )
        utc_day = datetime.now(UTC).date()
        try:
            with self._db.transaction() as conn:
                if not self._context_matches(conn, context, statuses=("running",)):
                    return False
                # Preserve the legacy whole-thread ceiling across UTC days and processes.
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
                    ("work-task-budget:" + context.budget_scope_id,),
                )
                task = conn.execute(
                    "SELECT COALESCE(SUM(used), 0) AS used FROM work_budget_counters "
                    "WHERE scope_kind='task' AND scope_id=?",
                    (context.budget_scope_id,),
                ).fetchone()
                if int(_read(task, "used")) >= 20:
                    return False
                inserted = conn.execute(
                    "INSERT INTO work_external_attempts(attempt_id, run_id, budget_scope_id, "
                    "work_user_id, organization_id, runtime_id, capability, utc_day, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved') "
                    "ON CONFLICT(attempt_id) DO NOTHING RETURNING attempt_id",
                    (
                        attempt_id,
                        context.run_id,
                        context.budget_scope_id,
                        context.work_user_id,
                        context.organization_id,
                        context.runtime_id,
                        capability,
                        utc_day,
                    ),
                ).fetchone()
                if inserted is None:
                    return False
                scopes = (
                    ("task", context.budget_scope_id, 20),
                    ("user", context.work_user_id, 100),
                    ("organization", context.organization_id, 500),
                )
                for kind, scope_id, limit in scopes:
                    row = conn.execute(
                        "INSERT INTO work_budget_counters(scope_kind, scope_id, utc_day, used) "
                        "VALUES (?, ?, ?, 1) ON CONFLICT(scope_kind, scope_id, utc_day) "
                        "DO UPDATE SET used=work_budget_counters.used+1 "
                        "WHERE work_budget_counters.used < ? RETURNING used",
                        (kind, scope_id, utc_day, limit),
                    ).fetchone()
                    if row is None:
                        raise _BudgetLimitReached
                return True
        except _BudgetLimitReached:
            return False

    def finish_attempt(self, attempt_id: str, status: str) -> None:
        if status not in {"completed", "uncertain"}:
            raise ValueError("invalid external attempt status")
        if not self._executor_is_live():
            return
        if self._secured:
            self._secure_call("work_finish_attempt", self._executor_id, attempt_id, status)
            return
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE work_external_attempts e SET status=?, finished_at=now() "
                "FROM work_runs r WHERE e.run_id=r.run_id AND e.attempt_id=? "
                "AND e.runtime_id=? AND r.executor_id=? AND e.status='reserved'",
                (status, attempt_id, self.runtime_id, self._executor_id),
            )
