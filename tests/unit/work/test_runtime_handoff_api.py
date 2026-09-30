from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from work_platform.authorization import ExecutionGrant
from work_platform.runtime_adapter import RuntimeBinding

from octop.api.deps import decode_token, resolve_user_from_token
from octop.api.routers.work_runtime import RuntimeHandoffRequest, exchange_handoff
from octop.infra.errors import OctopError
from octop.infra.work.routing import resolve_entry_route


def _binding() -> RuntimeBinding:
    return RuntimeBinding(
        "org-b",
        "runtime-b",
        "role-b",
        "volume-b",
        "database-b",
        "https://runtime-b.internal:8080",
        "handoff-b",
    )


def _grant() -> ExecutionGrant:
    return ExecutionGrant(
        octop_user_id=42,
        work_user_id="work-user-b",
        organization_id="org-b",
        agent_id="agent-b",
        member_status="active",
        membership_revision=3,
        policy_revision=2,
        runtime=_binding(),
    )


class Directory:
    expected_runtime_binding = _binding()

    def resolve_entry_grant(self, _octop_user_id: int, _agent_id: str) -> ExecutionGrant:
        return _grant()

    def resolve_runtime_grant(self, _work_user_id: str, _agent_id: str) -> ExecutionGrant:
        return _grant()

    def consume_runtime_handoff(self, _handoff: object) -> ExecutionGrant:
        return _grant()


@pytest.mark.asyncio
async def test_target_mints_its_own_short_lived_session_after_rechecking_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "handoff-b").write_bytes(b"runtime-b-secret-runtime-b-secret-00")
    route = resolve_entry_route(Directory(), 7, "agent-b", tmp_path, connection_id="b" * 32)
    runtime_jwt_secret = b"target-runtime-jwt-secret-32-bytes"
    user = SimpleNamespace(id=42, username="runtime-b-user", role="user")
    runtime = SimpleNamespace(
        work_control_plane=Directory(),
        user_manager=SimpleNamespace(get_by_id=lambda user_id: user if user_id == 42 else None),
    )
    server = SimpleNamespace(
        app_runtime=runtime,
        user_manager=runtime.user_manager,
        services=SimpleNamespace(
            secret_repo=SimpleNamespace(get=lambda name: runtime_jwt_secret),
            settings_repo=SimpleNamespace(get=lambda name: None),
        ),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(octop_server=server)))
    monkeypatch.setenv("WORK_RUNTIME_SECRETS_DIR", str(tmp_path))

    response = await exchange_handoff(
        RuntimeHandoffRequest(token=route.handoff_token),
        request,
        connection_id=route.connection_id,
    )

    payload = decode_token(runtime_jwt_secret, response.access_token)
    assert payload["sub"] == 42
    assert payload["uname"] == "runtime-b-user"
    assert payload["work_connection_id"] == "b" * 32
    with pytest.raises(OctopError):
        resolve_user_from_token(server, response.access_token)
    with pytest.raises(OctopError):
        resolve_user_from_token(
            server,
            response.access_token,
            work_connection_id="c" * 32,
        )
    assert response.runtime_id == "runtime-b"
    assert response.connection_id == "b" * 32


@pytest.mark.asyncio
async def test_target_rejects_when_handoff_consumption_store_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnavailableDirectory(Directory):
        def consume_runtime_handoff(self, _handoff: object) -> ExecutionGrant:
            raise RuntimeError("database unavailable")

    (tmp_path / "handoff-b").write_bytes(b"runtime-b-secret-runtime-b-secret-00")
    route = resolve_entry_route(Directory(), 7, "agent-b", tmp_path, connection_id="b" * 32)
    runtime = SimpleNamespace(
        work_control_plane=UnavailableDirectory(),
        user_manager=SimpleNamespace(get_by_id=lambda _user_id: None),
    )
    server = SimpleNamespace(app_runtime=runtime, services=None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(octop_server=server)))
    monkeypatch.setenv("WORK_RUNTIME_SECRETS_DIR", str(tmp_path))

    with pytest.raises(RuntimeError, match="database unavailable"):
        await exchange_handoff(
            RuntimeHandoffRequest(token=route.handoff_token),
            request,
            connection_id=route.connection_id,
        )
