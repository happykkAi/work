"""Real authority-DB boundary checks, only on the disposable PostgreSQL test DB."""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import get_context

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from work_platform.authorization import issue_execution_context
from work_platform.runtime_adapter import RuntimeBinding
from work_platform.runtime_handoff import issue_runtime_handoff, verify_runtime_handoff

from octop.infra.db.pool import PostgresPool
from octop.infra.work.control_plane import WorkControlPlane
from octop.infra.work.permissions import provision_principal
from tests.integration.test_postgresql_control_plane import _reset_public_schema
from tests.support.postgresql import requires_postgresql


def _compete(args):
    url, binding, uid = args
    control = WorkControlPlane(url, binding.runtime_id, expected_runtime_binding=binding)
    try:
        context, _ = issue_execution_context(
            control,
            octop_user_id=uid,
            agent_id="agent-" + binding.organization_id,
            run_id=uuid.uuid4().hex,
            budget_scope_id=uuid.uuid4().hex,
        )
        assert control.activate_run(context)
        result = control.reserve_attempt(context, "model:local_stub", uuid.uuid4().hex)
        control.finish_run(context, "completed")
        return os.getpid(), result
    finally:
        control.close()


@requires_postgresql
@pytest.mark.postgresql
def test_runtime_authority_writes_denied_but_scoped_manager_and_business_work():
    admin_url = os.environ["OCTOP_TEST_DATABASE_URL"]
    pool = PostgresPool(admin_url)
    try:
        _reset_public_schema(pool)
    finally:
        pool.close()
    migration = WorkControlPlane(admin_url, "migration")
    migration.close()
    suffix = uuid.uuid4().hex[:12]
    roles = {key: "work_test_" + key + suffix for key in ("a", "b", "manager")}
    urls = {}
    controls = []
    with psycopg.connect(admin_url, autocommit=True) as admin:
        try:
            for key, role in roles.items():
                password = uuid.uuid4().hex
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
                urls[key] = make_conninfo(admin_url, user=role, password=password)
                provision_principal(
                    admin_url,
                    role,
                    kind="manager" if key == "manager" else "runtime",
                    runtime_id=None if key == "manager" else "runtime-" + key,
                    organization_id="org-" + ("a" if key == "manager" else key),
                )
            admin.execute("INSERT INTO work_users VALUES('shared-user','active')")
            for key, uid in (("a", 1), ("b", 2)):
                org, rid, aid = "org-" + key, "runtime-" + key, "agent-org-" + key
                admin.execute(
                    "INSERT INTO work_identities VALUES(%s,%s,'shared-user','active')", (rid, uid)
                )
                admin.execute(
                    "INSERT INTO work_memberships VALUES(%s,'shared-user','member','active',1)",
                    (org,),
                )
                admin.execute("INSERT INTO work_organization_policies VALUES(%s,1,TRUE)", (org,))
                admin.execute(
                    "INSERT INTO work_agent_bindings VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'active')",
                    (
                        aid,
                        org,
                        rid,
                        "octop-" + key,
                        "volume-" + key,
                        "secret-" + key,
                        "https://runtime-" + key + ".internal:8088",
                        "handoff-" + key,
                    ),
                )
                for cap in ("model:local_stub", "tool:feishu", "tool:pixelrag"):
                    admin.execute(
                        "INSERT INTO work_capabilities VALUES(%s,%s,TRUE,TRUE)", (org, cap)
                    )
            binding = RuntimeBinding(
                "org-a",
                "runtime-a",
                "octop-a",
                "volume-a",
                "secret-a",
                "https://runtime-a.internal:8088",
                "handoff-a",
            )
            control = WorkControlPlane(urls["a"], "runtime-a", expected_runtime_binding=binding)
            controls.append(control)
            assert control._secured is True
            assert control.resolve_grant(1, "agent-org-a") is not None
            assert control.resolve_runtime_grant("shared-user", "agent-org-b") is None
            with psycopg.connect(urls["a"], autocommit=True) as runtime:
                assert runtime.execute(
                    "SELECT organization_id FROM work_memberships"
                ).fetchall() == [("org-a",)]
                attacks = (
                    "UPDATE work_organization_policies SET available=TRUE",
                    "INSERT INTO work_memberships VALUES('org-b','shared-user','owner','active',9)",
                    "DELETE FROM work_budget_counters",
                    "UPDATE work_capabilities SET enabled=TRUE",
                    "DELETE FROM work_runtime_handoffs",
                    "TRUNCATE work_runs CASCADE",
                    "ALTER TABLE work_runs ADD COLUMN forged INTEGER",
                    "CREATE TABLE public.forged(id INTEGER)",
                    "SET ROLE " + roles["manager"],
                    "SELECT public.work_manage_policy('org-a','tool:feishu',TRUE,FALSE)",
                )
                for attack in attacks:
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        runtime.execute(attack)
            context, _ = issue_execution_context(
                control,
                octop_user_id=1,
                agent_id="agent-org-a",
                run_id="run-a",
                budget_scope_id="task-a",
            )
            assert control.activate_run(context)
            assert control.reserve_attempt(context, "model:local_stub", "attempt-a")
            assert not control.reserve_attempt(context, "tool:feishu", "retired-a")
            assert not control.reserve_attempt(context, "tool:pixelrag", "retired-b")
            payload = control._json_payload(context)
            with psycopg.connect(urls["a"], autocommit=True) as runtime:
                forged = dict(payload.obj, organization_id="org-b", runtime_id="runtime-b")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute(
                        "SELECT work_create_run(%s,%s)",
                        (psycopg.types.json.Jsonb(forged), control._executor_id),
                    )
                assert runtime.execute(
                    "SELECT work_reserve_attempt(%s,%s,%s,%s)",
                    (
                        psycopg.types.json.Jsonb(forged),
                        control._executor_id,
                        "model:local_stub",
                        "forged",
                    ),
                ).fetchone() == (False,)
            secret = b"synthetic-handoff-secret-00000000"
            handoff = verify_runtime_handoff(
                issue_runtime_handoff(
                    binding,
                    work_user_id="shared-user",
                    agent_id="agent-org-a",
                    connection_id="a" * 32,
                    secret=secret,
                ),
                runtime_id="runtime-a",
                secret=secret,
            )
            assert control.consume_runtime_handoff(handoff) is not None
            assert control.consume_runtime_handoff(handoff) is None
            # Each authority row must remain locked across the validation-to-reservation gap.
            for table, condition in (
                ("work_users", "work_user_id='shared-user'"),
                ("work_identities", "runtime_id='runtime-a' AND octop_user_id=1"),
                ("work_agent_bindings", "agent_id='agent-org-a'"),
            ):
                admin.execute(
                    "SELECT pg_advisory_lock(hashtextextended('work-task-budget:task-a',0))"
                )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    pending = executor.submit(
                        control.reserve_attempt, context, "model:local_stub", "race-" + table
                    )
                    try:
                        deadline = time.monotonic() + 5
                        waiting = False
                        while time.monotonic() < deadline:
                            waiting = admin.execute(
                                "SELECT EXISTS(SELECT 1 FROM pg_locks l JOIN pg_stat_activity s "
                                "ON s.pid=l.pid WHERE NOT l.granted AND l.locktype='advisory' "
                                "AND s.usename=%s)",
                                (roles["a"],),
                            ).fetchone()[0]
                            if waiting:
                                break
                            time.sleep(0.02)
                        assert waiting, "reservation did not reach the controlled lock boundary"
                        revoked = False
                        with psycopg.connect(admin_url, autocommit=True) as revoker:
                            revoker.execute("SET lock_timeout='200ms'")
                            try:
                                revoker.execute(
                                    sql.SQL("UPDATE {} SET status='disabled' WHERE ").format(
                                        sql.Identifier(table)
                                    )
                                    + sql.SQL(condition)
                                )
                                revoked = True
                            except psycopg.errors.LockNotAvailable:
                                pass
                    finally:
                        admin.execute(
                            "SELECT pg_advisory_unlock(hashtextextended('work-task-budget:task-a',0))"
                        )
                    accepted = pending.result(timeout=5)
                assert not (revoked and accepted), (
                    table + ": revoked first, yet execution remained eligible"
                )
                admin.execute(
                    sql.SQL("UPDATE {} SET status='active' WHERE ").format(sql.Identifier(table))
                    + sql.SQL(condition)
                )
            terminal, _ = issue_execution_context(
                control,
                octop_user_id=1,
                agent_id="agent-org-a",
                run_id="terminal-run",
                budget_scope_id="terminal-task",
            )
            assert control.activate_run(terminal)
            assert control.reserve_attempt(terminal, "model:local_stub", "terminal-attempt")
            control.finish_run(terminal, "failed")
            with psycopg.connect(urls["manager"], autocommit=True) as manager:
                assert manager.execute(
                    "SELECT work_manage_policy('org-a','model:local_stub',TRUE,TRUE)"
                ).fetchone() == (2,)
                for org, cap in (
                    ("org-b", "model:local_stub"),
                    ("org-a", "tool:feishu"),
                    ("org-a", "tool:pixelrag"),
                ):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        manager.execute("SELECT work_manage_policy(%s,%s,TRUE,TRUE)", (org, cap))
            assert not control.context_is_current(context)
            # Global user UTC allowance remains shared across independent institution roles.
            admin.execute("UPDATE work_budget_counters SET used=99 WHERE scope_kind='user'")
            binding_b = RuntimeBinding(
                "org-b",
                "runtime-b",
                "octop-b",
                "volume-b",
                "secret-b",
                "https://runtime-b.internal:8088",
                "handoff-b",
            )
            with ProcessPoolExecutor(
                max_workers=2, mp_context=get_context("spawn"), max_tasks_per_child=1
            ) as executor:
                results = list(
                    executor.map(_compete, [(urls["a"], binding, 1), (urls["b"], binding_b, 2)])
                )
            assert len({pid for pid, _ in results}) == 2
            assert sum(accepted for _, accepted in results) == 1
            assert admin.execute(
                "SELECT used FROM work_budget_counters WHERE scope_kind='user'"
            ).fetchone() == (100,)
            control.close()
            controls.clear()
            restarted = WorkControlPlane(urls["a"], "runtime-a", expected_runtime_binding=binding)
            controls.append(restarted)
            assert admin.execute(
                "SELECT status FROM work_runs WHERE run_id='terminal-run'"
            ).fetchone() == ("failed",)
            assert admin.execute(
                "SELECT status FROM work_external_attempts WHERE attempt_id='terminal-attempt'"
            ).fetchone() == ("uncertain",)
            assert restarted.consume_runtime_handoff(handoff) is None
            assert restarted.resolve_grant(1, "agent-org-a") is not None
            with (
                psycopg.connect(urls["a"], autocommit=True) as runtime,
                pytest.raises(psycopg.errors.InsufficientPrivilege),
            ):
                runtime.execute("UPDATE work_organization_policies SET revision=1")
        finally:
            for control in controls:
                control.close()
            for role in roles.values():
                admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
