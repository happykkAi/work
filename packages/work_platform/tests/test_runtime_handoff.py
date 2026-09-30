from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from work_platform.runtime_adapter import RuntimeBinding
from work_platform.runtime_handoff import issue_runtime_handoff, verify_runtime_handoff


def _binding(organization_id: str, runtime_id: str) -> RuntimeBinding:
    return RuntimeBinding(
        organization_id=organization_id,
        runtime_id=runtime_id,
        database_role=f"role-{runtime_id}",
        volume_id=f"volume-{runtime_id}",
        secret_ref=f"database-{runtime_id}",
        endpoint=f"https://{runtime_id}.internal:8080",
        handoff_secret_ref=f"handoff-{runtime_id}",
    )


def test_handoff_is_scoped_to_the_server_selected_runtime() -> None:
    now = datetime(2026, 9, 28, 8, tzinfo=UTC)
    runtime_a = _binding("org-a", "runtime-a")
    token = issue_runtime_handoff(
        runtime_a,
        work_user_id="work-user-a",
        agent_id="agent-a",
        connection_id="a" * 32,
        secret=b"runtime-a-secret-runtime-a-secret-00",
        now=now,
    )

    handoff = verify_runtime_handoff(
        token,
        runtime_id="runtime-a",
        secret=b"runtime-a-secret-runtime-a-secret-00",
        now=now + timedelta(seconds=5),
    )

    assert handoff.work_user_id == "work-user-a"
    assert handoff.organization_id == "org-a"
    assert handoff.agent_id == "agent-a"
    assert handoff.runtime_id == "runtime-a"
    assert handoff.purpose == "runtime-handoff"
    assert handoff.connection_id == "a" * 32

    with pytest.raises(PermissionError):
        verify_runtime_handoff(
            token,
            runtime_id="runtime-b",
            secret=b"runtime-b-secret-runtime-b-secret-00",
            now=now + timedelta(seconds=5),
        )


def test_handoff_rejects_a_token_for_another_purpose() -> None:
    now = datetime(2026, 9, 28, 8, tzinfo=UTC)
    secret = b"runtime-a-secret-runtime-a-secret-00"
    token = jwt.encode(
        {
            "iss": "work-entry",
            "aud": "runtime-a",
            "sub": "work-user-a",
            "organization_id": "org-a",
            "agent_id": "agent-a",
            "connection_id": "a" * 32,
            "runtime_id": "runtime-a",
            "purpose": "browser-session",
            "jti": "handoff-id",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=30)).timestamp()),
        },
        secret,
        algorithm="HS256",
    )

    with pytest.raises(PermissionError):
        verify_runtime_handoff(token, runtime_id="runtime-a", secret=secret, now=now)


def test_expired_handoff_is_rejected() -> None:
    now = datetime(2026, 9, 28, 8, tzinfo=UTC)
    token = issue_runtime_handoff(
        _binding("org-a", "runtime-a"),
        work_user_id="work-user-a",
        agent_id="agent-a",
        connection_id="a" * 32,
        secret=b"runtime-a-secret-runtime-a-secret-00",
        now=now,
        ttl=timedelta(seconds=10),
    )

    with pytest.raises(PermissionError):
        verify_runtime_handoff(
            token,
            runtime_id="runtime-a",
            secret=b"runtime-a-secret-runtime-a-secret-00",
            now=now + timedelta(seconds=11),
        )
