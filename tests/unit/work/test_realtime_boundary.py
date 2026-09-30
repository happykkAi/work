import asyncio
from types import SimpleNamespace

import pytest
from psycopg.errors import AdminShutdown
from starlette.websockets import WebSocketDisconnect

from octop.api.middleware.work_boundary import WorkBoundary
from octop.infra.errors import ErrorCode, OctopError


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_work_database_restart_before_router_returns_503(started):
    async def unavailable(scope, receive, send):
        if started:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        raise AdminShutdown("synthetic PostgreSQL restart")

    server = SimpleNamespace(app_runtime=SimpleNamespace(work_entry_mode=True))
    sent = []

    async def send(message):
        sent.append(message)

    request = WorkBoundary(unavailable, server)(
        {"type": "http", "path": "/api/internal/work/handoff", "query_string": b""},
        unavailable,
        send,
    )
    if started:
        with pytest.raises(AdminShutdown):
            await request
        assert len(sent) == 1
        assert sent[0]["status"] == 200
        return
    await request
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 503


def test_framework_log_redacts_all_query_encodings():
    import logging

    from octop.infra.server import RequestQueryRedaction

    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "",
        0,
        '%s - "WebSocket %s"',
        ("client", "/api/chat/ws?%74oken=secret&safe=1"),
        None,
    )
    RequestQueryRedaction().filter(record)
    assert record.getMessage() == 'client - "WebSocket /api/chat/ws"'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,query,origin",
    [
        ("/api/agents/b/chat/ws", b"token=secret", None),
        ("/api/agents/b/chat/ws", b"%61ccess_token=secret", None),
        ("/api/agents/b/chat/ws", b"", "https://evil.invalid"),
        ("/api/agents/b/terminal/ws", b"", None),
        ("/api/desktop-stream/ws", b"", None),
        ("/api/mobile-stream/ws", b"", None),
        ("/api/browser-stream/ws", b"", None),
    ],
)
async def test_work_rejects_legacy_credentials_origin_and_control_routes(path, query, origin):
    async def unreachable(*args):
        pytest.fail("blocked request reached router")

    server = SimpleNamespace(
        app_runtime=SimpleNamespace(work_entry_mode=True),
        services=SimpleNamespace(config=SimpleNamespace(cors_origins=[])),
    )
    headers = [
        (b"host", b"localhost"),
        (b"sec-websocket-protocol", b"octop.chat,octop.auth.secret"),
    ]
    if origin:
        headers.append((b"origin", origin.encode()))
    sent = []

    async def send(message):
        sent.append(message)

    await WorkBoundary(unreachable, server)(
        {"type": "websocket", "path": path, "query_string": query, "headers": headers},
        unreachable,
        send,
    )
    assert sent == [{"type": "websocket.close", "code": 4003}]


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke, direction", [(True, "receive"), (True, "send"), (False, "send")])
async def test_work_rechecks_session_and_membership(monkeypatch, revoke, direction):
    active = True

    def resolve(*args, **kwargs):
        if not active and revoke:
            raise OctopError(ErrorCode.AUTH_FAILED, "revoked")
        return SimpleNamespace(id=1)

    monkeypatch.setattr("octop.api.middleware.work_boundary.resolve_user_from_token", resolve)
    control = SimpleNamespace(resolve_entry_grant=lambda *args: object() if active else None)
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(work_entry_mode=True, work_control_plane=control),
        services=SimpleNamespace(config=SimpleNamespace(cors_origins=[])),
    )
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "websocket.receive", "text": "protected"}

    async def route(scope, receive, send):
        nonlocal active
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.send", "text": "allowed"})
        active = False
        if direction == "receive":
            await receive()
        else:
            await send({"type": "websocket.send", "text": "forbidden"})
        pytest.fail("revoked operation was accepted")

    await WorkBoundary(route, server)(
        {
            "type": "websocket",
            "path": "/api/agents/b/chat/ws",
            "query_string": b"",
            "headers": [
                (b"host", b"localhost"),
                (b"origin", b"http://localhost"),
                (b"sec-websocket-protocol", b"octop.chat,octop.auth.secret"),
            ],
        },
        receive,
        send,
    )
    assert sent == [
        {"type": "websocket.accept"},
        {"type": "websocket.send", "text": "allowed"},
        {"type": "websocket.close", "code": 4001 if revoke else 4003},
    ]


@pytest.mark.asyncio
async def test_forwarded_token_expiry_is_only_relaxed_after_accept(monkeypatch):
    calls = []

    def resolve(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id=1)

    monkeypatch.setattr("octop.api.middleware.work_boundary.resolve_user_from_token", resolve)
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(
            work_entry_mode=False,
            work_execution_required=True,
            work_control_plane=SimpleNamespace(resolve_grant=lambda *args: object()),
        )
    )

    async def route(scope, receive, send):
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.send", "text": "allowed"})

    async def send(message):
        pass

    await WorkBoundary(route, server)(
        {
            "type": "websocket",
            "path": "/api/agents/b/chat/ws",
            "query_string": b"",
            "headers": [
                (b"authorization", b"Bearer scoped"),
                (b"x-work-connection-id", b"connection"),
            ],
        },
        send,
        send,
    )
    assert [c["allow_expired"] for c in calls] == [False, False, True]
    assert all(c["work_connection_id"] == "connection" for c in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/api/agents/b/chat/ws", "/api/work/v1/agents/b/chat/ws", "/api/notifications/ws"],
)
async def test_work_closes_idle_revoked_session(monkeypatch, path):
    active = True

    def resolve(*args, **kwargs):
        if not active:
            raise OctopError(ErrorCode.AUTH_FAILED, "revoked")
        return SimpleNamespace(id=1)

    monkeypatch.setattr("octop.api.middleware.work_boundary.resolve_user_from_token", resolve)
    monkeypatch.setattr(
        "octop.api.middleware.work_boundary._SESSION_RECHECK_SECONDS", 0.01, raising=False
    )
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(
            work_entry_mode=True,
            work_control_plane=SimpleNamespace(resolve_entry_grant=lambda *args: object()),
        )
    )
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        await asyncio.Event().wait()

    async def route(scope, receive, send):
        nonlocal active
        await send({"type": "websocket.accept"})
        active = False
        try:
            await receive()
        except WebSocketDisconnect:
            active = True  # A stale hub callback must not revive a closed connection.
        await send({"type": "websocket.send", "text": "forbidden"})

    await asyncio.wait_for(
        WorkBoundary(route, server)(
            {
                "type": "websocket",
                "path": path,
                "query_string": b"",
                "headers": [(b"sec-websocket-protocol", b"octop.chat,octop.auth.secret")],
            },
            receive,
            send,
        ),
        0.2,
    )
    assert sent == [
        {"type": "websocket.accept"},
        {"type": "websocket.close", "code": 4001},
    ]
