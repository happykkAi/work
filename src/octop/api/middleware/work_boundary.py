"""First-release Work realtime boundary; standalone Octop remains unchanged."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from psycopg import OperationalError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from octop.api.deps import extract_websocket_auth, resolve_user_from_token
from octop.infra.errors import OctopError

_CHAT = re.compile(r"^/api/(?:work/v1/)?agents/([^/]+)/chat/ws$")
_SESSION_RECHECK_SECONDS = 5.0


class WorkBoundary:
    def __init__(self, app: ASGIApp, server: Any) -> None:
        self.app = app
        self.server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        runtime = self.server.app_runtime
        if (
            scope["type"] not in {"http", "websocket"}
            or runtime is None
            or not (runtime.work_entry_mode or runtime.work_execution_required)
        ):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        query = parse_qs(scope.get("query_string", b"").decode(), keep_blank_values=True)
        chat = _CHAT.fullmatch(path)
        blocked = bool({"token", "access_token"} & query.keys())
        # No remote-control or ancillary live streams in the first Work release.
        blocked |= any(
            part in path.split("/")
            for part in (
                "browser",
                "browser-stream",
                "desktop",
                "desktop-stream",
                "mobile",
                "mobile-stream",
                "terminal",
            )
        ) or path.endswith(("/trajectory/stream", "/chat/hitl/resume"))
        if scope["type"] == "http":
            if blocked:
                await JSONResponse(
                    {"detail": "Work endpoint or URL credentials disabled"}, status_code=403
                )(scope, receive, send)
            else:
                started = False

                async def checked_http_send(message: Message) -> None:
                    nonlocal started
                    if message["type"] == "http.response.start":
                        started = True
                    await send(message)

                try:
                    await self.app(scope, receive, checked_http_send)
                except OperationalError:
                    if started:
                        raise
                    await JSONResponse({"detail": "Work database unavailable"}, status_code=503)(
                        scope, receive, send
                    )
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            configured = self.server.services.config.cors_origins
            blocked |= origin not in configured and not (
                parsed.scheme in {"http", "https"}
                and parsed.netloc == headers.get("host")
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and parsed.username is None
                and parsed.password is None
            )
        blocked |= chat is None and path != "/api/notifications/ws"
        if blocked:
            await send({"type": "websocket.close", "code": 4003})
            return
        connection_id = headers.get("x-work-connection-id", "").strip()
        token, _ = extract_websocket_auth(
            query_token=None,
            authorization=headers.get("authorization"),
            protocol_header=headers.get("sec-websocket-protocol"),
            forwarded=bool(connection_id),
        )
        closed = False
        established = False
        send_lock = asyncio.Lock()

        def authorize() -> None:
            if not token:
                raise WebSocketDisconnect(4001)
            try:
                user = resolve_user_from_token(
                    self.server,
                    token,
                    work_connection_id=connection_id or None,
                    allow_expired=established and bool(connection_id),
                )
                if chat:
                    control = runtime.work_control_plane
                    if control is None:
                        raise WebSocketDisconnect(4003)
                    resolve = (
                        control.resolve_entry_grant
                        if runtime.work_entry_mode
                        else control.resolve_grant
                    )
                    if resolve(user.id, chat[1]) is None:
                        raise WebSocketDisconnect(4003)
            except OctopError as exc:
                raise WebSocketDisconnect(4001) from exc

        async def ensure_authorized() -> None:
            nonlocal closed
            if closed:
                raise WebSocketDisconnect(4001)
            try:
                authorize()
            except WebSocketDisconnect as exc:
                # Routers and push hubs may swallow disconnects; close at the boundary.
                if not closed:
                    closed = True
                    await send({"type": "websocket.close", "code": exc.code})
                raise

        async def checked_receive() -> Message:
            while True:
                try:
                    message = await asyncio.wait_for(receive(), _SESSION_RECHECK_SECONDS)
                    break
                except TimeoutError:
                    async with send_lock:
                        await ensure_authorized()
            if message["type"] != "websocket.disconnect":
                async with send_lock:
                    await ensure_authorized()
            return message

        async def checked_send(message: Message) -> None:
            nonlocal closed, established
            async with send_lock:
                if message["type"] in {"websocket.accept", "websocket.send"}:
                    await ensure_authorized()
                if message["type"] == "websocket.close":
                    if closed:
                        return
                    closed = True
                await send(message)
                if message["type"] == "websocket.accept":
                    established = True

        try:
            authorize()
            await self.app(scope, checked_receive, checked_send)
        except WebSocketDisconnect as exc:
            if not closed:
                await send({"type": "websocket.close", "code": exc.code})
