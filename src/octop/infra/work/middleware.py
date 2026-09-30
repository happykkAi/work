"""Per-model and per-tool authorization for the Octop Harness graph."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ToolCallRequest
from work_platform.authorization import WorkAccessDenied, authorize_external
from work_platform.runtime_context import ExecutionContext

from octop.infra.work.control_plane import WorkControlPlane
from octop.infra.work.execution import current_work_execution

logger = logging.getLogger(__name__)


def _log_attempt(
    event: str,
    context: ExecutionContext,
    attempt_id: str,
    capability: str,
) -> None:
    logger.info(
        event,
        extra={
            "work_connection_id": context.connection_id,
            "work_run_id": context.run_id,
            "work_attempt_id": attempt_id,
            "work_runtime_id": context.runtime_id,
            "work_organization_id": context.organization_id,
            "work_agent_id": context.agent_id,
            "work_capability": capability,
        },
    )


def _model_capability(model: Any) -> str:
    explicit = getattr(model, "work_capability", None)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    module = next(
        (
            base.__module__.split(".", maxsplit=1)[0]
            for base in type(model).__mro__
            if base.__module__.startswith("langchain_")
            and not base.__module__.startswith("langchain_core")
        ),
        type(model).__module__.split(".", maxsplit=1)[0],
    )
    provider = module.removeprefix("langchain_") or type(model).__name__.lower()
    model_id = getattr(model, "model_name", None) or getattr(model, "model", None)
    return f"model:{provider}/{model_id}" if model_id else f"model:{provider}"


def _tool_capability(request: ToolCallRequest) -> str:
    raw = request.tool_call.get("name")
    name = raw.strip() if isinstance(raw, str) else ""
    return f"tool:{name}" if name else "tool:unknown"


def _current() -> tuple[ExecutionContext, WorkControlPlane]:
    execution = current_work_execution()
    if execution is None:
        raise WorkAccessDenied("active Work execution context required")
    return execution.context, execution.control_plane


class WorkExecutionMiddleware(AgentMiddleware[Any, Any]):
    """Fail closed unless the current queued run still has member, policy and budget."""

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Any],
    ) -> Any:
        context, control = _current()
        attempt_id = uuid.uuid4().hex
        capability = _model_capability(request.model)

        def invoke() -> Any:
            _log_attempt("work_external_attempt_started", context, attempt_id, capability)
            try:
                result = handler(request)
            except BaseException:
                control.finish_attempt(attempt_id, "uncertain")
                _log_attempt("work_external_attempt_uncertain", context, attempt_id, capability)
                raise
            control.finish_attempt(attempt_id, "completed")
            _log_attempt("work_external_attempt_completed", context, attempt_id, capability)
            return result

        return authorize_external(
            context,
            capability,
            control,
            attempt_id=attempt_id,
            operation=invoke,
        )

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[Any]],
    ) -> Any:
        context, control = _current()
        attempt_id = uuid.uuid4().hex
        capability = _model_capability(request.model)

        async def invoke() -> Any:
            _log_attempt("work_external_attempt_started", context, attempt_id, capability)
            try:
                result = await handler(request)
            except BaseException:
                await asyncio.to_thread(control.finish_attempt, attempt_id, "uncertain")
                _log_attempt("work_external_attempt_uncertain", context, attempt_id, capability)
                raise
            await asyncio.to_thread(control.finish_attempt, attempt_id, "completed")
            _log_attempt("work_external_attempt_completed", context, attempt_id, capability)
            return result

        pending = await asyncio.to_thread(
            authorize_external,
            context,
            capability,
            control,
            attempt_id=attempt_id,
            operation=invoke,
        )
        return await pending

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        context, control = _current()
        attempt_id = uuid.uuid4().hex
        capability = _tool_capability(request)

        def invoke() -> Any:
            _log_attempt("work_external_attempt_started", context, attempt_id, capability)
            try:
                result = handler(request)
            except BaseException:
                control.finish_attempt(attempt_id, "uncertain")
                _log_attempt("work_external_attempt_uncertain", context, attempt_id, capability)
                raise
            control.finish_attempt(attempt_id, "completed")
            _log_attempt("work_external_attempt_completed", context, attempt_id, capability)
            return result

        return authorize_external(
            context,
            capability,
            control,
            attempt_id=attempt_id,
            operation=invoke,
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        context, control = _current()
        attempt_id = uuid.uuid4().hex
        capability = _tool_capability(request)

        async def invoke() -> Any:
            _log_attempt("work_external_attempt_started", context, attempt_id, capability)
            try:
                result = await handler(request)
            except BaseException:
                await asyncio.to_thread(control.finish_attempt, attempt_id, "uncertain")
                _log_attempt("work_external_attempt_uncertain", context, attempt_id, capability)
                raise
            await asyncio.to_thread(control.finish_attempt, attempt_id, "completed")
            _log_attempt("work_external_attempt_completed", context, attempt_id, capability)
            return result

        pending = await asyncio.to_thread(
            authorize_external,
            context,
            capability,
            control,
            attempt_id=attempt_id,
            operation=invoke,
        )
        return await pending
