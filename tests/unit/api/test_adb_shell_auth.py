from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.websockets import WebSocketState
from tests.support.fakes import fake_bin_path

from octop.api.routers.mobile import shell_ws


class _FakeWs:
    def __init__(self) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(octop_server=object()))
        self.headers = {"Sec-WebSocket-Protocol": "octop.chat, octop.auth.header.payload.signature"}
        self.application_state = WebSocketState.CONNECTING
        self.accepted_subprotocol: str | None = None
        self.close_code: int | None = None

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_subprotocol = subprotocol
        self.application_state = WebSocketState.CONNECTED

    async def send_text(self, _text: str) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.close_code = code
        self.application_state = WebSocketState.DISCONNECTED


@pytest.mark.asyncio
async def test_adb_shell_accepts_token_from_subprotocol_without_query() -> None:
    ws = _FakeWs()
    with (
        patch.object(shell_ws, "os", SimpleNamespace(name="posix")),
        patch.object(shell_ws, "find_adb", return_value=fake_bin_path("adb")),
        patch.object(shell_ws, "list_devices", return_value=[]),
        patch.object(
            shell_ws,
            "resolve_user_from_token",
            return_value=SimpleNamespace(id=1, permissions=["mobile"]),
        ),
        patch.object(shell_ws, "user_has_permission", return_value=True),
    ):
        await shell_ws.adb_shell_ws(ws, token=None, serial="missing")  # type: ignore[arg-type]

    assert ws.accepted_subprotocol == "octop.chat"
    assert ws.close_code == 4003
