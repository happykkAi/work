"""Unified Work WebSocket entry that proxies to a server-selected runtime."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from octop.api.deps import extract_websocket_auth, resolve_user_from_token
from octop.api.routers.work_runtime import RuntimeHandoffResponse
from octop.infra.errors import OctopError
from octop.infra.work.routing import RuntimeRoute, resolve_entry_route
from octop.infra.work.tls import runtime_client_ssl_context

logger = logging.getLogger(__name__)
router = APIRouter()


def runtime_urls(endpoint: str, agent_id: str) -> tuple[str, str]:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not agent_id.strip()
    ):
        raise ValueError("invalid Work runtime endpoint")
    base = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    encoded_agent = quote(agent_id, safe="")
    return (
        f"{base}/api/internal/work/handoff",
        f"wss://{parsed.netloc}/api/agents/{encoded_agent}/chat/ws",
    )


def runtime_websocket_headers(access_token: str, connection_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Work-Connection-ID": connection_id,
    }


async def exchange_runtime_token(route: RuntimeRoute, agent_id: str) -> tuple[str, str]:
    handoff_url, websocket_url = runtime_urls(route.endpoint, agent_id)
    tls = runtime_client_ssl_context()
    async with httpx.AsyncClient(
        timeout=5.0, follow_redirects=False, trust_env=False, verify=tls
    ) as client:
        response = await client.post(
            handoff_url,
            json={"token": route.handoff_token},
            headers={"X-Work-Connection-ID": route.connection_id},
        )
        response.raise_for_status()
    payload = RuntimeHandoffResponse.model_validate(response.json())
    if payload.runtime_id != route.binding.runtime_id:
        raise PermissionError("runtime handoff response target mismatch")
    if payload.connection_id != route.connection_id:
        raise PermissionError("runtime handoff response connection mismatch")
    return websocket_url, payload.access_token


async def _browser_to_runtime(websocket: WebSocket, upstream: ClientConnection) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            await upstream.close()
            return
        if message.get("text") is not None:
            await upstream.send(message["text"])
        elif message.get("bytes") is not None:
            await upstream.send(message["bytes"])


async def _runtime_to_browser(websocket: WebSocket, upstream: ClientConnection) -> None:
    async for message in upstream:
        if isinstance(message, str):
            await websocket.send_text(message)
        else:
            await websocket.send_bytes(message)


async def _relay(websocket: WebSocket, upstream: ClientConnection) -> None:
    tasks = {
        asyncio.create_task(_browser_to_runtime(websocket, upstream)),
        asyncio.create_task(_runtime_to_browser(websocket, upstream)),
    }
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done | pending:
        with contextlib.suppress(asyncio.CancelledError, ConnectionClosed, WebSocketDisconnect):
            await task


@router.websocket("/work/v1/agents/{agent_id}/chat/ws")
async def work_entry_chat_ws(
    websocket: WebSocket,
    agent_id: str,
    token: str | None = Query(default=None),
) -> None:
    server = websocket.app.state.octop_server
    runtime = server.app_runtime
    control = runtime.work_control_plane if runtime is not None else None
    secret_dir = os.environ.get("WORK_RUNTIME_SECRETS_DIR", "").strip()
    token, accepted_subprotocol = extract_websocket_auth(
        query_token=token,
        authorization=None,
        protocol_header=websocket.headers.get("Sec-WebSocket-Protocol"),
        forwarded=False,
    )
    if (
        not token
        or control is None
        or not runtime.work_entry_mode
        or control.expected_runtime_binding is not None
        or not secret_dir
    ):
        await websocket.close(code=4003, reason="Work entry authorization unavailable")
        return
    try:
        user = resolve_user_from_token(server, token)
        connection_id = uuid.uuid4().hex
        route = resolve_entry_route(
            control,
            user.id,
            agent_id,
            Path(secret_dir),
            connection_id=connection_id,
        )
        websocket_url, runtime_token = await exchange_runtime_token(route, agent_id)
    except (OctopError, PermissionError, RuntimeError, ValueError, httpx.HTTPError):
        logger.warning("work_runtime_route_denied", extra={"work_agent_id": agent_id})
        await websocket.close(code=4003, reason="Work runtime route denied")
        return

    try:
        async with connect(
            websocket_url,
            ssl=runtime_client_ssl_context(),
            additional_headers=runtime_websocket_headers(runtime_token, route.connection_id),
            proxy=None,
            open_timeout=5.0,
            close_timeout=5.0,
        ) as upstream:
            await websocket.accept(subprotocol=accepted_subprotocol)
            logger.info(
                "work_runtime_route_opened",
                extra={
                    "work_runtime_id": route.binding.runtime_id,
                    "work_organization_id": route.binding.organization_id,
                    "work_agent_id": agent_id,
                    "work_connection_id": route.connection_id,
                },
            )
            await _relay(websocket, upstream)
    except (OSError, RuntimeError, TimeoutError, ConnectionClosed, InvalidHandshake):
        logger.exception(
            "work_runtime_route_failed",
            extra={
                "work_runtime_id": route.binding.runtime_id,
                "work_agent_id": agent_id,
                "work_connection_id": route.connection_id,
            },
        )
        with contextlib.suppress(Exception):
            await websocket.close(code=1011, reason="Work runtime unavailable")
