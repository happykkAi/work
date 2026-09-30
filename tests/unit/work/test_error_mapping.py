from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from websockets.exceptions import InvalidHandshake

from octop.api.routers import work_entry, work_runtime


@pytest.mark.asyncio
async def test_upstream_handshake_failure_closes_browser(monkeypatch):
    control = SimpleNamespace(expected_runtime_binding=None)
    runtime = SimpleNamespace(work_control_plane=control, work_entry_mode=True)
    websocket = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(octop_server=SimpleNamespace(app_runtime=runtime))
        ),
        headers={},
        close=AsyncMock(),
    )
    route = SimpleNamespace(connection_id="c" * 32, binding=SimpleNamespace(runtime_id="b"))
    monkeypatch.setenv("WORK_RUNTIME_SECRETS_DIR", "/synthetic")
    monkeypatch.setattr(work_entry, "resolve_user_from_token", lambda *_: SimpleNamespace(id=1))
    monkeypatch.setattr(work_entry, "resolve_entry_route", lambda *_, **kw: route)
    monkeypatch.setattr(
        work_entry, "exchange_runtime_token", AsyncMock(return_value=("wss://b", "test"))
    )
    monkeypatch.setattr(work_entry, "runtime_client_ssl_context", lambda: None)

    def fail(*args, **kwargs):
        raise InvalidHandshake("synthetic handshake failure")

    monkeypatch.setattr(work_entry, "connect", fail)
    await work_entry.work_entry_chat_ws(websocket, "agent-b", "synthetic")
    websocket.close.assert_awaited_once_with(code=1011, reason="Work runtime unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [LookupError("config"), OSError("secret"), ValueError("config")],
)
async def test_handoff_configuration_failure_returns_503(monkeypatch, error):
    def fail():
        raise error

    binding = SimpleNamespace(require_handoff=fail)
    runtime = SimpleNamespace(work_control_plane=SimpleNamespace(expected_runtime_binding=binding))
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(octop_server=SimpleNamespace(app_runtime=runtime))
        ),
    )
    monkeypatch.setenv("WORK_RUNTIME_SECRETS_DIR", "/synthetic")
    with pytest.raises(HTTPException) as caught:
        await work_runtime.exchange_handoff(
            work_runtime.RuntimeHandoffRequest(token="synthetic"),
            request,
            "c" * 32,
        )
    assert caught.value.status_code == 503
