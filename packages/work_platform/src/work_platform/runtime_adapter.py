"""Resolve one Work context to exactly one institution runtime."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass

from work_platform.runtime_context import ExecutionContext


@dataclass(frozen=True, slots=True)
class RuntimeBinding:
    organization_id: str
    runtime_id: str
    database_role: str
    volume_id: str
    secret_ref: str
    endpoint: str | None = None
    handoff_secret_ref: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.organization_id,
                self.runtime_id,
                self.database_role,
                self.volume_id,
                self.secret_ref,
            )
        ):
            raise ValueError("runtime binding fields must not be empty")
        if self.endpoint is not None and not self.endpoint.strip():
            raise ValueError("runtime endpoint must not be empty")
        if self.handoff_secret_ref is not None and not self.handoff_secret_ref.strip():
            raise ValueError("runtime handoff secret reference must not be empty")

    def require_handoff(self) -> tuple[str, str]:
        if self.endpoint is None or self.handoff_secret_ref is None:
            raise LookupError("runtime binding has no trusted handoff route")
        return self.endpoint, self.handoff_secret_ref

    @classmethod
    def from_environment(
        cls,
        *,
        runtime_id: str,
        database_role: str | None,
    ) -> RuntimeBinding | None:
        organization_id = os.environ.get("WORK_ORGANIZATION_ID", "").strip()
        volume_id = os.environ.get("WORK_VOLUME_ID", "").strip()
        secret_ref = os.environ.get("WORK_SECRET_REF", "").strip()
        endpoint = os.environ.get("WORK_RUNTIME_ENDPOINT", "").strip() or None
        handoff_secret_ref = os.environ.get("WORK_HANDOFF_SECRET_REF", "").strip() or None
        if not all(
            (runtime_id.strip(), database_role or "", organization_id, volume_id, secret_ref)
        ):
            return None
        return cls(
            organization_id=organization_id,
            runtime_id=runtime_id.strip(),
            database_role=(database_role or "").strip(),
            volume_id=volume_id,
            secret_ref=secret_ref,
            endpoint=endpoint,
            handoff_secret_ref=handoff_secret_ref,
        )


def resolve_runtime(
    context: ExecutionContext,
    bindings: Iterable[RuntimeBinding],
    *,
    requested_organization_id: str | None = None,
) -> RuntimeBinding:
    if not context.is_current():
        raise PermissionError("execution context expired")
    if requested_organization_id and requested_organization_id != context.organization_id:
        raise PermissionError("requested organization does not match execution context")
    matches = [item for item in bindings if item.organization_id == context.organization_id]
    if len(matches) != 1:
        raise LookupError("organization runtime must resolve to exactly one binding")
    return matches[0]
