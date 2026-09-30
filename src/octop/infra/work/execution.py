"""Run-scoped server authorization propagated through Gateway execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

from work_platform.authorization import WorkAccessDenied
from work_platform.capability_policy import CapabilityDenied, PolicyUnavailable
from work_platform.runtime_context import ExecutionContext

from octop.infra.work.control_plane import WorkControlPlane


@dataclass(frozen=True, slots=True)
class WorkExecution:
    context: ExecutionContext
    control_plane: WorkControlPlane


@dataclass
class WorkRunOutcome:
    failed: bool = False


_current_execution: ContextVar[WorkExecution | None] = ContextVar(
    "octop_work_execution", default=None
)


def current_work_execution() -> WorkExecution | None:
    return _current_execution.get()


def bind_work_execution(
    context: ExecutionContext, control_plane: WorkControlPlane
) -> Token[WorkExecution | None]:
    return _current_execution.set(WorkExecution(context, control_plane))


def reset_work_execution(token: Token[WorkExecution | None]) -> None:
    _current_execution.reset(token)


async def require_work_execution(*, agent_id: str, thread_id: str) -> WorkExecution:
    execution = current_work_execution()
    if (
        execution is None
        or execution.context.agent_id != agent_id
        or execution.context.budget_scope_id != thread_id
        or not await asyncio.to_thread(
            execution.control_plane.context_is_current, execution.context
        )
    ):
        raise WorkAccessDenied("active Work execution context required")
    return execution


@asynccontextmanager
async def work_run_scope(
    context: ExecutionContext,
    control_plane: WorkControlPlane,
    outcome: WorkRunOutcome | None = None,
) -> AsyncIterator[WorkRunOutcome]:
    current = current_work_execution()
    if current is not None:
        if current.context.run_id != context.run_id:
            raise WorkAccessDenied("nested Work execution context mismatch")
        yield outcome or WorkRunOutcome()
        return

    if not await asyncio.to_thread(control_plane.activate_run, context):
        await asyncio.to_thread(control_plane.block_run, context)
        raise WorkAccessDenied("queued Work run is no longer authorized")
    token = bind_work_execution(context, control_plane)
    result = outcome or WorkRunOutcome()
    try:
        yield result
    except BaseException as exc:
        status = (
            "blocked"
            if isinstance(exc, (WorkAccessDenied, CapabilityDenied, PolicyUnavailable))
            else "failed"
        )
        await asyncio.to_thread(control_plane.finish_run, context, status)
        raise
    else:
        status = "failed" if result.failed else "completed"
        await asyncio.to_thread(control_plane.finish_run, context, status)
    finally:
        reset_work_execution(token)
