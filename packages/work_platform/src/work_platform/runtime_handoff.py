"""Short-lived, runtime-scoped identity handoff from the Work entry service."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from work_platform.runtime_adapter import RuntimeBinding

_ISSUER = "work-entry"
_PURPOSE = "runtime-handoff"
_MAX_TTL = timedelta(seconds=60)
_CONNECTION_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class RuntimeHandoff:
    connection_id: str
    work_user_id: str
    organization_id: str
    agent_id: str
    runtime_id: str
    purpose: str
    handoff_id: str
    issued_at: datetime
    expires_at: datetime


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("handoff time must be timezone-aware")
    return current


def _require_secret(secret: bytes) -> None:
    if len(secret) < 32:
        raise ValueError("runtime handoff secret must contain at least 32 bytes")


def issue_runtime_handoff(
    binding: RuntimeBinding,
    *,
    work_user_id: str,
    agent_id: str,
    connection_id: str,
    secret: bytes,
    now: datetime | None = None,
    ttl: timedelta = timedelta(seconds=30),
) -> str:
    binding.require_handoff()
    _require_secret(secret)
    if (
        not work_user_id.strip()
        or not agent_id.strip()
        or _CONNECTION_ID.fullmatch(connection_id) is None
    ):
        raise ValueError("handoff identity fields must not be empty")
    if ttl <= timedelta(0) or ttl > _MAX_TTL:
        raise ValueError("runtime handoff ttl must be between 1 and 60 seconds")
    issued_at = _now(now)
    expires_at = issued_at + ttl
    return jwt.encode(
        {
            "iss": _ISSUER,
            "aud": binding.runtime_id,
            "sub": work_user_id,
            "organization_id": binding.organization_id,
            "agent_id": agent_id,
            "connection_id": connection_id,
            "runtime_id": binding.runtime_id,
            "purpose": _PURPOSE,
            "jti": uuid.uuid4().hex,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        secret,
        algorithm="HS256",
    )


def verify_runtime_handoff(
    token: str,
    *,
    runtime_id: str,
    secret: bytes,
    now: datetime | None = None,
) -> RuntimeHandoff:
    _require_secret(secret)
    current = _now(now)
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=runtime_id,
            issuer=_ISSUER,
            options={
                "require": [
                    "agent_id",
                    "aud",
                    "connection_id",
                    "exp",
                    "iat",
                    "iss",
                    "jti",
                    "organization_id",
                    "purpose",
                    "runtime_id",
                    "sub",
                ],
                "verify_exp": False,
            },
        )
        issued_at = datetime.fromtimestamp(int(payload["iat"]), UTC)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), UTC)
        values = {
            "connection_id": payload["connection_id"],
            "work_user_id": payload["sub"],
            "organization_id": payload["organization_id"],
            "agent_id": payload["agent_id"],
            "runtime_id": payload["runtime_id"],
            "purpose": payload["purpose"],
            "handoff_id": payload["jti"],
        }
        if not all(isinstance(value, str) and value.strip() for value in values.values()):
            raise ValueError("invalid runtime handoff claims")
        if _CONNECTION_ID.fullmatch(values["connection_id"]) is None:
            raise ValueError("invalid runtime handoff connection")
        if values["runtime_id"] != runtime_id:
            raise ValueError("runtime handoff target mismatch")
        if values["purpose"] != _PURPOSE:
            raise ValueError("runtime handoff purpose mismatch")
        if issued_at > current or expires_at <= current or expires_at - issued_at > _MAX_TTL:
            raise ValueError("runtime handoff is outside its validity window")
    except (KeyError, TypeError, ValueError, jwt.InvalidTokenError) as exc:
        raise PermissionError("invalid runtime handoff") from exc
    return RuntimeHandoff(
        **values,
        issued_at=issued_at,
        expires_at=expires_at,
    )
