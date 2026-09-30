"""Private Work entry-to-runtime identity exchange."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from octop.api.deps import sign_token
from octop.infra.work.routing import exchange_runtime_handoff, load_runtime_secret

logger = logging.getLogger(__name__)
router = APIRouter()


class RuntimeHandoffRequest(BaseModel):
    token: str


class RuntimeHandoffResponse(BaseModel):
    access_token: str
    connection_id: str
    runtime_id: str


@router.post("/internal/work/handoff", response_model=RuntimeHandoffResponse)
async def exchange_handoff(
    payload: RuntimeHandoffRequest,
    request: Request,
    connection_id: str = Header(alias="X-Work-Connection-ID"),
) -> RuntimeHandoffResponse:
    server = request.app.state.octop_server
    runtime = server.app_runtime
    control = runtime.work_control_plane if runtime is not None else None
    binding = control.expected_runtime_binding if control is not None else None
    secret_dir = os.environ.get("WORK_RUNTIME_SECRETS_DIR", "").strip()
    if (
        control is None
        or binding is None
        or getattr(runtime, "work_entry_mode", False)
        or not secret_dir
    ):
        raise HTTPException(status_code=503, detail="Work runtime handoff is unavailable")
    try:
        _endpoint, secret_ref = binding.require_handoff()
        secret = load_runtime_secret(Path(secret_dir), secret_ref)
        grant = exchange_runtime_handoff(
            control,
            binding,
            secret,
            payload.token,
            connection_id=connection_id,
        )
        user = runtime.user_manager.get_by_id(grant.octop_user_id)
        jwt_secret = server.services.secret_repo.get("jwt") if server.services is not None else None
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Work runtime handoff denied") from exc
    except (LookupError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Work runtime configuration unavailable"
        ) from exc

    if user is None or jwt_secret is None:
        raise HTTPException(status_code=403, detail="Work runtime handoff denied")
    logger.info(
        "work_runtime_handoff_accepted",
        extra={
            "work_runtime_id": binding.runtime_id,
            "work_organization_id": binding.organization_id,
            "work_agent_id": grant.agent_id,
            "work_connection_id": connection_id,
        },
    )
    return RuntimeHandoffResponse(
        access_token=sign_token(
            jwt_secret,
            sub=user.id,
            uname=user.username,
            role=user.role,
            ttl_seconds=60,
            work_connection_id=connection_id,
        ),
        connection_id=connection_id,
        runtime_id=binding.runtime_id,
    )
