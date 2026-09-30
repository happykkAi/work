"""Dashboard chat over WebSocket — routes turns through Gateway / GlobalProcessor."""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState
from work_platform.authorization import (
    WorkAccessDenied,
    issue_execution_context,
    require_active_grant,
)

from octop.api.common.agent import assert_agent_access
from octop.api.deps import extract_websocket_auth, resolve_user_from_token
from octop.api.routers.chat.models import UserTurnWsFrame
from octop.api.routers.chat.sse import json_chunk_default
from octop.api.routers.chat.turn import (
    build_dashboard_inbound,
    prepare_dashboard_turn,
    turn_has_content,
)
from octop.infra.errors import OctopError
from octop.infra.gateway.ws import WS_CHANNEL_ID

logger = logging.getLogger(__name__)

router = APIRouter()


def websocket_auth_token(
    query_token: str | None,
    authorization: str | None,
    *,
    forwarded: bool,
) -> str | None:
    token, _subprotocol = extract_websocket_auth(
        query_token=query_token,
        authorization=authorization,
        protocol_header=None,
        forwarded=forwarded,
    )
    return token


@router.websocket("/agents/{agent_id}/chat/ws")
async def dashboard_chat_ws(
    websocket: WebSocket,
    agent_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Bidirectional Dashboard chat. Wire protocol mirrors harness stream chunks."""
    server = websocket.app.state.octop_server
    runtime = server.app_runtime
    if runtime is not None and runtime.work_entry_mode:
        from octop.api.routers.work_entry import work_entry_chat_ws  # noqa: PLC0415

        await work_entry_chat_ws(websocket, agent_id, token)
        return
    forwarded_connection_id = websocket.headers.get("X-Work-Connection-ID", "").strip()
    token, accepted_subprotocol = extract_websocket_auth(
        query_token=token,
        authorization=websocket.headers.get("Authorization"),
        protocol_header=websocket.headers.get("Sec-WebSocket-Protocol"),
        forwarded=bool(forwarded_connection_id),
    )
    if not token:
        await websocket.close(code=4001, reason="missing token")
        return

    try:
        user = resolve_user_from_token(
            server,
            token,
            work_connection_id=forwarded_connection_id or None,
        )
    except OctopError as exc:
        await websocket.close(code=4001, reason=f"auth: {exc.code.value}")
        return

    assert runtime is not None  # noqa: S101
    gateway = runtime.gateway
    hub = gateway.ws_hub
    channel_manager = gateway.channel_manager
    if channel_manager is None:
        await websocket.close(code=1011, reason="gateway not ready")
        return

    try:
        assert_agent_access(server, agent_id, user)
    except OctopError as exc:
        from octop.infra.errors import ErrorCode  # noqa: PLC0415

        code = 4003 if exc.code == ErrorCode.FORBIDDEN else 4404
        await websocket.close(code=code, reason=str(exc.code.value))
        return

    work_execution_required = runtime.work_execution_required
    control_plane = runtime.work_control_plane
    if work_execution_required:
        try:
            if control_plane is None:
                raise WorkAccessDenied("Work execution authorization is not configured")
            require_active_grant(
                control_plane,
                octop_user_id=user.id,
                agent_id=agent_id,
            )
        except WorkAccessDenied:
            await websocket.close(code=4003, reason="active Work membership is required")
            return

    if (
        work_execution_required
        and control_plane is not None
        and getattr(control_plane, "expected_runtime_binding", None) is not None
        and not forwarded_connection_id
    ):
        await websocket.close(code=4003, reason="Work connection identity is required")
        return
    connection_id = (
        forwarded_connection_id
        if work_execution_required and forwarded_connection_id
        else uuid.uuid4().hex
    )
    await websocket.accept(subprotocol=accepted_subprotocol)

    async def send_frame(frame: dict[str, Any]) -> None:
        if websocket.application_state != WebSocketState.CONNECTED:
            return
        await websocket.send_text(
            json.dumps(frame, ensure_ascii=False, default=json_chunk_default),
        )

    hub.register(connection_id, send_frame)

    try:
        while websocket.application_state == WebSocketState.CONNECTED:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"type": "user_turn", "text": raw}

            if not isinstance(payload, dict):
                continue

            msg_type = str(payload.get("type") or "user_turn")
            if msg_type == "ping":
                await send_frame({"type": "pong"})
                continue

            if work_execution_required:
                try:
                    if control_plane is None:
                        raise WorkAccessDenied("Work execution authorization is not configured")
                    require_active_grant(
                        control_plane,
                        octop_user_id=user.id,
                        agent_id=agent_id,
                    )
                except WorkAccessDenied:
                    await send_frame(
                        {"type": "error", "message": "Active Work membership is required"}
                    )
                    await send_frame({"type": "done"})
                    continue

            if msg_type == "subscribe":
                thread_id = str(payload.get("thread_id") or "").strip()
                if not thread_id:
                    await send_frame({"type": "error", "message": "subscribe requires thread_id"})
                    continue
                row = gateway.thread_registry.get_thread(thread_id)
                if row is None or row.agent_id != agent_id or row.user_id != user.id:
                    await send_frame(
                        {"type": "error", "message": f"thread {thread_id!r} not found"},
                    )
                    continue
                hub.subscribe(thread_id, connection_id)
                await send_frame(
                    {
                        "type": "turn_status",
                        "thread_id": thread_id,
                        "active": hub.is_turn_active(thread_id),
                    },
                )
                continue

            if msg_type == "cancel":
                thread_id = str(payload.get("thread_id") or "").strip()
                if not thread_id:
                    await send_frame({"type": "error", "message": "cancel requires thread_id"})
                    continue
                row = gateway.thread_registry.get_thread(thread_id)
                if row is None or row.agent_id != agent_id or row.user_id != user.id:
                    await send_frame(
                        {"type": "error", "message": f"thread {thread_id!r} not found"},
                    )
                    continue
                server.app_runtime.agent_registry.cancel_stream(agent_id, thread_id)
                continue

            if msg_type != "user_turn":
                await send_frame({"type": "error", "message": f"unknown message type: {msg_type}"})
                continue

            try:
                frame = UserTurnWsFrame.model_validate({**payload, "type": "user_turn"})
            except ValidationError as exc:
                await send_frame({"type": "error", "message": str(exc)})
                await send_frame({"type": "done"})
                continue

            turn = frame.to_turn_body()
            if not turn_has_content(turn):
                await send_frame({"type": "error", "message": "empty message"})
                await send_frame({"type": "done"})
                continue

            try:
                prepared = await prepare_dashboard_turn(
                    server,
                    agent_id=agent_id,
                    user=user,
                    turn=turn,
                )
            except OctopError as exc:
                await send_frame({"type": "error", "message": str(exc)})
                await send_frame({"type": "done"})
                continue

            work_context = None
            if work_execution_required:
                if control_plane is None:
                    await send_frame(
                        {
                            "type": "error",
                            "message": "Work execution authorization is not configured",
                        },
                    )
                    await send_frame({"type": "done"})
                    continue
                try:
                    work_context, _runtime = issue_execution_context(
                        control_plane,
                        octop_user_id=user.id,
                        agent_id=agent_id,
                        run_id=uuid.uuid4().hex,
                        budget_scope_id=prepared.thread_id,
                        connection_id=connection_id,
                    )
                except WorkAccessDenied:
                    await send_frame(
                        {"type": "error", "message": "Active Work membership is required"},
                    )
                    await send_frame({"type": "done"})
                    continue

            inbound = build_dashboard_inbound(
                agent_id=agent_id,
                user_id=user.id,
                prepared=prepared,
                turn=turn,
                ws_connection_id=connection_id,
                user_is_admin=bool(getattr(user, "is_admin", False)),
                work_execution_context=work_context,
            )
            hub.subscribe(prepared.thread_id, connection_id)
            try:
                channel_manager.enqueue(WS_CHANNEL_ID, inbound)
            except Exception:
                if control_plane is not None and work_context is not None:
                    try:
                        control_plane.block_run(work_context)
                    except Exception:
                        logger.exception("work_chat_block_run_failed run=%s", work_context.run_id)
                    logger.exception(
                        "work_chat_enqueue_failed",
                        extra={
                            "work_connection_id": connection_id,
                            "work_run_id": work_context.run_id,
                            "work_runtime_id": work_context.runtime_id,
                            "work_organization_id": work_context.organization_id,
                            "work_agent_id": agent_id,
                        },
                    )
                else:
                    logger.exception("Dashboard chat enqueue failed agent=%s", agent_id)
                await send_frame({"type": "error", "message": "Work task could not be queued"})
                await send_frame({"type": "done"})

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("dashboard chat ws error agent=%s", agent_id)
        if websocket.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await send_frame({"type": "error", "message": "internal error"})
    finally:
        # Disconnect must not cancel an in-flight turn — clients may reconnect and
        # subscribe to continue receiving subsequent chunks (weak stream resume).
        hub.unregister(connection_id)
        if websocket.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close()
