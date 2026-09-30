from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

try:
    from work_platform.authorization import (
        ExecutionGrant,
        WorkAccessDenied,
        require_active_grant,
    )
    from work_platform.capability_policy import (
        CapabilityDenied,
        CapabilityPolicy,
        PolicyUnavailable,
        dispatch_external,
    )
    from work_platform.runtime_adapter import RuntimeBinding, resolve_runtime
    from work_platform.runtime_context import ExecutionContext
except ImportError as exc:
    ExecutionGrant = WorkAccessDenied = require_active_grant = None
    CapabilityDenied = CapabilityPolicy = PolicyUnavailable = None
    RuntimeBinding = resolve_runtime = ExecutionContext = dispatch_external = None
    _import_error = exc
else:
    _import_error = None


class ExecutionBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        if ExecutionContext is None:
            self.fail(f"Work platform authorization imports are unavailable: {_import_error}")
        self.now = datetime.now(UTC)
        self.org_a = ExecutionContext(
            work_user_id="user-a",
            organization_id="org-a",
            project_id="project-a",
            workspace_scope="org-a/project-a/user-a",
            run_id="run-a",
            budget_scope_id="budget-a",
            policy_revision=1,
            membership_revision=3,
            allowed_asset_versions=frozenset({"asset-a:v1"}),
            issued_at=self.now,
            expires_at=self.now + timedelta(minutes=5),
        )
        self.runtimes = (
            RuntimeBinding("org-a", "unit-a", "work_a", "work-a", "secret-a"),
            RuntimeBinding("org-b", "unit-b", "work_b", "work-b", "secret-b"),
        )

    def test_preflight_requires_the_requested_active_member_and_runtime(self):
        self.assertIsNotNone(require_active_grant, f"identity resolver missing: {_import_error}")
        runtime = RuntimeBinding("org-a", "unit-a", "work_a", "work-a", "secret-a")

        class Directory:
            grant = ExecutionGrant(
                octop_user_id=41,
                work_user_id="work-user-a",
                organization_id="org-a",
                agent_id="agent-a",
                member_status="active",
                membership_revision=1,
                policy_revision=1,
                runtime=runtime,
            )

            def resolve_grant(self, user_id, agent_id):
                if user_id != 41 or agent_id != "agent-a":
                    return None
                return self.grant

        self.assertEqual(
            require_active_grant(Directory(), octop_user_id=41, agent_id="agent-a"),
            Directory.grant,
        )
        with self.assertRaises(WorkAccessDenied):
            require_active_grant(Directory(), octop_user_id=41, agent_id="agent-b")

        Directory.grant = replace(Directory.grant, member_status="suspended")
        with self.assertRaises(WorkAccessDenied):
            require_active_grant(Directory(), octop_user_id=41, agent_id="agent-a")

    def test_a_cannot_address_b_runtime(self):
        self.assertIsNotNone(resolve_runtime, f"runtime resolver missing: {_import_error}")

        with self.assertRaises(PermissionError):
            resolve_runtime(self.org_a, self.runtimes, requested_organization_id="org-b")

    def test_two_synthetic_organizations_have_distinct_runtime_resources(self):
        self.assertIsNotNone(resolve_runtime, f"runtime resolver missing: {_import_error}")

        a = resolve_runtime(self.org_a, self.runtimes)
        org_b = replace(
            self.org_a,
            organization_id="org-b",
            work_user_id="user-b",
            workspace_scope="org-b/project-b/user-b",
            run_id="run-b",
            budget_scope_id="budget-b",
        )
        b = resolve_runtime(org_b, self.runtimes)

        self.assertEqual(
            (a.database_role, a.volume_id, a.secret_ref), ("work_a", "work-a", "secret-a")
        )
        self.assertEqual(
            (b.database_role, b.volume_id, b.secret_ref), ("work_b", "work-b", "secret-b")
        )

    def test_disabled_module_still_cannot_run_tool(self):
        for capability in (
            "feishu.create_table",
            "lark-cli.base",
            "larksuite.read",
            "pixelrag.search",
        ):
            calls = {"quota": 0, "token": 0, "business": 0}
            policy = CapabilityPolicy(enabled=frozenset({capability}))

            def operation(calls=calls):
                calls["quota"] += 1
                calls["token"] += 1
                calls["business"] += 1

            with self.subTest(capability=capability), self.assertRaises(CapabilityDenied):
                dispatch_external(self.org_a, capability, lambda policy=policy: policy, operation)

            self.assertEqual(calls, {"quota": 0, "token": 0, "business": 0})

    def test_unknown_tool_denied(self):
        policy = CapabilityPolicy(enabled=frozenset({"search.public"}))
        with self.assertRaises(CapabilityDenied):
            dispatch_external(self.org_a, "new_unreviewed_tool", lambda: policy, lambda: "sent")

    def test_policy_unavailable_blocks_egress(self):
        requests = []

        with self.assertRaises(PolicyUnavailable):
            dispatch_external(
                self.org_a, "search.public", lambda: None, lambda: requests.append("sent")
            )

        self.assertEqual(requests, [])

    def test_policy_error_and_expired_context_block_egress(self):
        requests = []

        def unavailable():
            raise RuntimeError("synthetic policy failure")

        with self.assertRaises(PolicyUnavailable):
            dispatch_external(
                self.org_a, "search.public", unavailable, lambda: requests.append("sent")
            )

        expired = replace(
            self.org_a,
            issued_at=self.now - timedelta(minutes=1),
            expires_at=self.now - timedelta(seconds=1),
        )
        with self.assertRaises(PolicyUnavailable):
            dispatch_external(
                expired,
                "search.public",
                lambda: CapabilityPolicy(frozenset()),
                lambda: requests.append("sent"),
            )

        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
