"""Server-side Work identity resolution and per-call authorization."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeVar

from work_platform.capability_policy import (
    CapabilityPolicy,
    PolicyUnavailable,
    dispatch_external,
)
from work_platform.runtime_adapter import RuntimeBinding
from work_platform.runtime_context import ExecutionContext

T = TypeVar("T")


class WorkAccessDenied(PermissionError):
    pass


class BudgetExhausted(WorkAccessDenied):
    pass


@dataclass(frozen=True, slots=True)
class ExecutionGrant:
    octop_user_id: int
    work_user_id: str
    organization_id: str
    agent_id: str
    member_status: str
    membership_revision: int
    policy_revision: int
    runtime: RuntimeBinding


class ExecutionDirectory(Protocol):
    def resolve_grant(self, octop_user_id: int, agent_id: str) -> ExecutionGrant | None: ...

    def create_run(self, context: ExecutionContext) -> None: ...

    def block_run(self, context: ExecutionContext) -> None: ...

    def context_is_current(self, context: ExecutionContext) -> bool: ...

    def load_policy(self, context: ExecutionContext) -> CapabilityPolicy | None: ...

    def reserve_attempt(
        self, context: ExecutionContext, capability: str, attempt_id: str
    ) -> bool: ...


def require_active_grant(
    directory: ExecutionDirectory,
    *,
    octop_user_id: int,
    agent_id: str,
) -> ExecutionGrant:
    """Resolve the signed-in Octop identity to an active member and runtime."""
    grant = directory.resolve_grant(octop_user_id, agent_id)
    if (
        grant is None
        or grant.octop_user_id != octop_user_id
        or grant.agent_id != agent_id
        or grant.member_status != "active"
        or grant.runtime.organization_id != grant.organization_id
    ):
        raise WorkAccessDenied("active Work membership and runtime binding required")
    return grant


def issue_execution_context(
    directory: ExecutionDirectory,
    *,
    octop_user_id: int,
    agent_id: str,
    run_id: str,
    budget_scope_id: str,
    connection_id: str | None = None,
    now: datetime | None = None,
    ttl: timedelta = timedelta(minutes=15),
) -> tuple[ExecutionContext, RuntimeBinding]:
    """Resolve a logged-in Octop user through persistent Work membership and runtime maps."""
    grant = require_active_grant(
        directory,
        octop_user_id=octop_user_id,
        agent_id=agent_id,
    )
    if ttl <= timedelta(0):
        raise ValueError("execution context ttl must be positive")

    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None:
        raise ValueError("execution context time must be timezone-aware")
    context = ExecutionContext(
        work_user_id=grant.work_user_id,
        organization_id=grant.organization_id,
        project_id=None,
        workspace_scope=(
            f"{grant.organization_id}/agent/{grant.agent_id}/user/{grant.work_user_id}"
        ),
        run_id=run_id or uuid.uuid4().hex,
        budget_scope_id=budget_scope_id,
        policy_revision=grant.policy_revision,
        membership_revision=grant.membership_revision,
        allowed_asset_versions=frozenset(),
        issued_at=issued_at,
        expires_at=issued_at + ttl,
        connection_id=connection_id or uuid.uuid4().hex,
        agent_id=grant.agent_id,
        runtime_id=grant.runtime.runtime_id,
        octop_user_id=grant.octop_user_id,
    )
    directory.create_run(context)
    return context, grant.runtime


def authorize_external(
    context: ExecutionContext | None,
    capability: str,
    directory: ExecutionDirectory,
    *,
    attempt_id: str | None = None,
    operation: Callable[[], T],
) -> T:
    """Recheck live membership, policy and budget immediately before an external call."""
    if context is None or not directory.context_is_current(context):
        raise WorkAccessDenied("execution membership or runtime authorization is no longer active")

    policy: CapabilityPolicy | None = None

    def load_policy() -> CapabilityPolicy | None:
        nonlocal policy
        policy = directory.load_policy(context)
        return policy

    def reserve_attempt(ctx: ExecutionContext, name: str) -> bool:
        if policy is None:
            raise PolicyUnavailable("capability policy unavailable")
        if name not in policy.billable:
            return True
        return directory.reserve_attempt(ctx, name, attempt_id or uuid.uuid4().hex)

    try:
        return dispatch_external(
            context,
            capability,
            load_policy,
            operation,
            validate_context=directory.context_is_current,
            reserve_attempt=reserve_attempt,
        )
    except PolicyUnavailable:
        raise
    except PermissionError as exc:
        if "budget" in str(exc):
            raise BudgetExhausted(str(exc)) from exc
        raise
