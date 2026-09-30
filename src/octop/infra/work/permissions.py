"""Migration-owner provisioning; runtime credentials never call this path."""

from __future__ import annotations

import psycopg
from psycopg import sql

_RUNTIME_FUNCTIONS = (
    "work_principal()",
    "work_register_executor(TEXT,TEXT)",
    "work_recover_runs(TEXT)",
    "work_create_run(JSONB,TEXT)",
    "work_run_transition(JSONB,TEXT,TEXT)",
    "work_reserve_attempt(JSONB,TEXT,TEXT,TEXT)",
    "work_finish_attempt(TEXT,TEXT,TEXT)",
    "work_consume_handoff(JSONB)",
)

# New Work business tables are private until a separately scoped read contract exists.
_RUNTIME_READ_TABLES = frozenset(
    {
        "work_schema_version",
        "work_users",
        "work_identities",
        "work_memberships",
        "work_agent_bindings",
        "work_organization_policies",
        "work_capabilities",
        "work_runs",
        "work_budget_counters",
        "work_external_attempts",
        "work_runtime_handoffs",
    }
)


def provision_principal(
    database_url: str,
    role: str,
    *,
    kind: str,
    runtime_id: str | None = None,
    organization_id: str | None = None,
) -> None:
    """Bind an existing restricted login to one immutable runtime/manager scope.

    The connection must be the migration owner; no password is accepted or logged.
    Repeated identical provisioning is allowed, rebinding an existing login is not.
    """
    if kind not in {"entry", "runtime", "manager"}:
        raise ValueError("invalid Work principal kind")
    if (kind != "manager" and not runtime_id) or (kind != "entry" and not organization_id):
        raise ValueError("Work principal scope is incomplete")
    with psycopg.connect(database_url) as conn:
        privileges = conn.execute(
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls "
            "OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) "
            "OR EXISTS(SELECT 1 FROM pg_class WHERE relowner=pg_roles.oid) "
            "FROM pg_roles WHERE rolname=%s",
            (role,),
        ).fetchone()
        if privileges is None or privileges[0]:
            raise ValueError(
                "Work login must not own tables, inherit roles or hold admin privileges"
            )
        previous = conn.execute(
            "SELECT runtime_id,organization_id,kind FROM public.work_database_principals "
            "WHERE role_name=%s",
            (role,),
        ).fetchone()
        if previous is not None and previous != (runtime_id, organization_id, kind):
            raise ValueError("existing Work database principal cannot be rebound")
        conn.execute(
            "INSERT INTO public.work_database_principals VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(role_name) DO NOTHING",
            (role, runtime_id, organization_id, kind),
        )
        ident = sql.Identifier(role)
        conn.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}, PUBLIC").format(ident))
        database = conn.execute("SELECT current_database()").fetchone()
        assert database is not None
        conn.execute(
            sql.SQL("REVOKE CREATE ON DATABASE {} FROM {}, PUBLIC").format(
                sql.Identifier(database[0]), ident
            )
        )
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident))
        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'work_%'"
        ).fetchall()
        for (table,) in tables:
            conn.execute(
                sql.SQL("REVOKE ALL ON TABLE public.{} FROM {}, PUBLIC").format(
                    sql.Identifier(table), ident
                )
            )
            if table in _RUNTIME_READ_TABLES and kind != "manager":
                conn.execute(
                    sql.SQL("GRANT SELECT ON TABLE public.{} TO {}").format(
                        sql.Identifier(table), ident
                    )
                )
        signatures = (
            ("work_manage_policy(TEXT,TEXT,BOOLEAN,BOOLEAN)",)
            if kind == "manager"
            else _RUNTIME_FUNCTIONS
        )
        for signature in signatures:
            conn.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION public.{} TO {}").format(
                    sql.SQL(signature), ident
                )
            )
