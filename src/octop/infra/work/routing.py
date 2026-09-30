"""Trusted Work entry routing and target-runtime identity exchange."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from work_platform.authorization import ExecutionGrant
from work_platform.runtime_adapter import RuntimeBinding
from work_platform.runtime_handoff import (
    RuntimeHandoff,
    issue_runtime_handoff,
    verify_runtime_handoff,
)

_SAFE_SECRET_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def work_entry_mode_enabled() -> bool:
    value = os.environ.get("WORK_ENTRY_MODE", "").strip().lower()
    if value in {"", "0", "false", "no"}:
        return False
    if value in {"1", "true", "yes"}:
        return True
    raise ValueError("WORK_ENTRY_MODE must be a boolean")


class RuntimeDirectory(Protocol):
    def resolve_entry_grant(self, octop_user_id: int, agent_id: str) -> ExecutionGrant | None: ...

    def resolve_runtime_grant(self, work_user_id: str, agent_id: str) -> ExecutionGrant | None: ...

    def consume_runtime_handoff(self, handoff: RuntimeHandoff) -> ExecutionGrant | None: ...


@dataclass(frozen=True, slots=True)
class RuntimeRoute:
    connection_id: str
    endpoint: str
    handoff_token: str
    binding: RuntimeBinding


def load_runtime_secret(directory: Path, secret_ref: str) -> bytes:
    if _SAFE_SECRET_REF.fullmatch(secret_ref) is None:
        raise PermissionError("invalid runtime secret reference")
    root = directory.resolve()
    try:
        path = (root / secret_ref).resolve(strict=True)
    except OSError as exc:
        raise PermissionError("runtime secret is unavailable") from exc
    if path.parent != root or not path.is_file():
        raise PermissionError("runtime secret is unavailable")
    secret = path.read_bytes().strip()
    if len(secret) < 32 or len(secret) > 4096:
        raise PermissionError("runtime secret has an invalid length")
    return secret


def resolve_entry_route(
    directory: RuntimeDirectory,
    octop_user_id: int,
    agent_id: str,
    secrets_directory: Path,
    *,
    connection_id: str,
) -> RuntimeRoute:
    grant = directory.resolve_entry_grant(octop_user_id, agent_id)
    if (
        grant is None
        or grant.member_status != "active"
        or grant.agent_id != agent_id
        or grant.organization_id != grant.runtime.organization_id
    ):
        raise PermissionError("active Work entry grant required")
    endpoint, secret_ref = grant.runtime.require_handoff()
    secret = load_runtime_secret(secrets_directory, secret_ref)
    token = issue_runtime_handoff(
        grant.runtime,
        work_user_id=grant.work_user_id,
        agent_id=grant.agent_id,
        connection_id=connection_id,
        secret=secret,
    )
    return RuntimeRoute(
        connection_id=connection_id,
        endpoint=endpoint,
        handoff_token=token,
        binding=grant.runtime,
    )


def exchange_runtime_handoff(
    directory: RuntimeDirectory,
    binding: RuntimeBinding,
    secret: bytes,
    token: str,
    *,
    connection_id: str,
) -> ExecutionGrant:
    handoff = verify_runtime_handoff(
        token,
        runtime_id=binding.runtime_id,
        secret=secret,
    )
    if not connection_id.strip() or handoff.connection_id != connection_id:
        raise PermissionError("runtime handoff connection mismatch")
    grant = directory.consume_runtime_handoff(handoff)
    if (
        grant is None
        or grant.member_status != "active"
        or grant.work_user_id != handoff.work_user_id
        or grant.organization_id != handoff.organization_id
        or grant.agent_id != handoff.agent_id
        or grant.runtime != binding
    ):
        raise PermissionError("runtime handoff is no longer authorized")
    return grant
