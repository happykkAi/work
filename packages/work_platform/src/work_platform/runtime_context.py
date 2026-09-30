"""Server-issued context required for institution-scoped execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

_CONNECTION_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    work_user_id: str
    organization_id: str
    project_id: str | None
    workspace_scope: str
    run_id: str
    budget_scope_id: str
    policy_revision: int
    membership_revision: int
    allowed_asset_versions: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    connection_id: str | None = None
    agent_id: str | None = None
    runtime_id: str | None = None
    octop_user_id: int | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.work_user_id,
                self.organization_id,
                self.workspace_scope,
                self.run_id,
                self.budget_scope_id,
            )
        ):
            raise ValueError("execution context identifiers must not be empty")
        if self.policy_revision < 0 or self.membership_revision < 0:
            raise ValueError("execution context revisions must be non-negative")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("execution context timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("execution context must expire after it is issued")
        if self.connection_id is not None and _CONNECTION_ID.fullmatch(self.connection_id) is None:
            raise ValueError("invalid execution connection identifier")
        if (self.agent_id is None) != (self.runtime_id is None):
            raise ValueError("agent and runtime identifiers must be present together")
        if self.agent_id is not None and not self.agent_id.strip():
            raise ValueError("agent identifier must not be empty")
        if self.runtime_id is not None and not self.runtime_id.strip():
            raise ValueError("runtime identifier must not be empty")

    def is_current(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return current.tzinfo is not None and self.issued_at <= current < self.expires_at
