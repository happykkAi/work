from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from os import environ
from unittest.mock import patch

from work_platform.authorization import (
    BudgetExhausted,
    ExecutionGrant,
    WorkAccessDenied,
    authorize_external,
    issue_execution_context,
)
from work_platform.capability_policy import CapabilityPolicy, PolicyUnavailable
from work_platform.runtime_adapter import RuntimeBinding


class Directory:
    def __init__(self) -> None:
        self.grant: ExecutionGrant | None = ExecutionGrant(
            octop_user_id=41,
            work_user_id="work-user-a",
            organization_id="org-a",
            agent_id="agent-a",
            member_status="active",
            membership_revision=4,
            policy_revision=2,
            runtime=RuntimeBinding("org-a", "runtime-a", "role-a", "volume-a", "secret-a"),
        )
        self.current = True
        self.policy: CapabilityPolicy | None = CapabilityPolicy(
            enabled=frozenset({"model:local_stub"}),
            billable=frozenset({"model:local_stub"}),
        )
        self.reservations: list[tuple[str, str]] = []
        self.runs: list[object] = []
        self.budget_available = True

    def resolve_grant(self, octop_user_id: int, agent_id: str) -> ExecutionGrant | None:
        if self.grant is None or (self.grant.octop_user_id, self.grant.agent_id) != (
            octop_user_id,
            agent_id,
        ):
            return None
        return self.grant

    def context_is_current(self, context: object) -> bool:
        return self.current

    def create_run(self, context: object) -> None:
        self.runs.append(context)

    def load_policy(self, context: object) -> CapabilityPolicy | None:
        return self.policy

    def reserve_attempt(self, context: object, capability: str, attempt_id: str) -> bool:
        if not self.budget_available:
            return False
        self.reservations.append((capability, attempt_id))
        return True


class TrustedIdentityTests(unittest.TestCase):
    def test_local_runtime_binding_requires_all_deployment_resources(self) -> None:
        values = {
            "WORK_ORGANIZATION_ID": "org-a",
            "WORK_VOLUME_ID": "org-a-data",
            "WORK_SECRET_REF": "org-a-database-url",
        }
        with patch.dict(environ, values, clear=True):
            binding = RuntimeBinding.from_environment(
                runtime_id="runtime-a", database_role="octop_a"
            )
        self.assertEqual(
            binding,
            RuntimeBinding("org-a", "runtime-a", "octop_a", "org-a-data", "org-a-database-url"),
        )

        with patch.dict(environ, {"WORK_ORGANIZATION_ID": "org-a"}, clear=True):
            self.assertIsNone(
                RuntimeBinding.from_environment(runtime_id="runtime-a", database_role="octop_a")
            )

    def test_context_uses_persistent_user_membership_and_agent_mapping(self) -> None:
        directory = Directory()
        context, runtime = issue_execution_context(
            directory,
            octop_user_id=41,
            agent_id="agent-a",
            run_id="run-1",
            budget_scope_id="thread-1",
            connection_id="b" * 32,
            now=datetime(2026, 9, 28, tzinfo=UTC),
        )

        self.assertEqual(context.work_user_id, "work-user-a")
        self.assertEqual(context.organization_id, "org-a")
        self.assertEqual(context.agent_id, "agent-a")
        self.assertEqual(context.runtime_id, "runtime-a")
        self.assertEqual(context.budget_scope_id, "thread-1")
        self.assertEqual(context.connection_id, "b" * 32)
        self.assertEqual(runtime.database_role, "role-a")

    def test_missing_or_inactive_member_is_denied(self) -> None:
        directory = Directory()
        directory.grant = replace(directory.grant, member_status="suspended")  # type: ignore[arg-type]

        with self.assertRaises(WorkAccessDenied):
            issue_execution_context(
                directory,
                octop_user_id=41,
                agent_id="agent-a",
                run_id="run-1",
                budget_scope_id="thread-1",
            )

        directory.grant = None
        with self.assertRaises(WorkAccessDenied):
            issue_execution_context(
                directory,
                octop_user_id=41,
                agent_id="agent-a",
                run_id="run-2",
                budget_scope_id="thread-1",
            )

    def test_agent_mapping_must_match_membership_organization(self) -> None:
        directory = Directory()
        directory.grant = replace(
            directory.grant,
            runtime=RuntimeBinding("org-b", "runtime-b", "role-b", "volume-b", "secret-b"),
        )  # type: ignore[arg-type]

        with self.assertRaises(WorkAccessDenied):
            issue_execution_context(
                directory,
                octop_user_id=41,
                agent_id="agent-a",
                run_id="run-1",
                budget_scope_id="thread-1",
            )

    def test_revoked_membership_blocks_before_operation(self) -> None:
        directory = Directory()
        context, _ = issue_execution_context(
            directory,
            octop_user_id=41,
            agent_id="agent-a",
            run_id="run-1",
            budget_scope_id="thread-1",
        )
        directory.current = False
        requests: list[str] = []

        with self.assertRaises(WorkAccessDenied):
            authorize_external(
                context,
                "model:local_stub",
                directory,
                attempt_id="attempt-1",
                operation=lambda: requests.append("sent"),
            )

        self.assertEqual(requests, [])
        self.assertEqual(directory.reservations, [])

    def test_policy_failure_and_budget_exhaustion_block_before_operation(self) -> None:
        directory = Directory()
        context, _ = issue_execution_context(
            directory,
            octop_user_id=41,
            agent_id="agent-a",
            run_id="run-1",
            budget_scope_id="thread-1",
        )
        requests: list[str] = []

        directory.policy = None
        with self.assertRaises(PolicyUnavailable):
            authorize_external(
                context,
                "model:local_stub",
                directory,
                attempt_id="attempt-1",
                operation=lambda: requests.append("sent"),
            )

        directory.policy = CapabilityPolicy(
            enabled=frozenset({"model:local_stub"}),
            billable=frozenset({"model:local_stub"}),
        )
        directory.budget_available = False
        with self.assertRaises(BudgetExhausted):
            authorize_external(
                context,
                "model:local_stub",
                directory,
                attempt_id="attempt-2",
                operation=lambda: requests.append("sent"),
            )

        self.assertEqual(requests, [])

    def test_allowed_call_reserves_before_running(self) -> None:
        directory = Directory()
        context, _ = issue_execution_context(
            directory,
            octop_user_id=41,
            agent_id="agent-a",
            run_id="run-1",
            budget_scope_id="thread-1",
        )
        events: list[str] = []
        directory.reserve_attempt = lambda *_args: events.append("reserved") or True

        result = authorize_external(
            context,
            "model:local_stub",
            directory,
            attempt_id="attempt-1",
            operation=lambda: events.append("request") or "ok",
        )

        self.assertEqual(result, "ok")
        self.assertEqual(events, ["reserved", "request"])


if __name__ == "__main__":
    unittest.main()
