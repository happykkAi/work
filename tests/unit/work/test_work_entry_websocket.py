from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from work_platform.runtime_context import ExecutionContext

from octop.api.deps import extract_websocket_auth
from octop.api.routers.chat.ws import dashboard_chat_ws, websocket_auth_token
from octop.api.routers.work_entry import runtime_urls, runtime_websocket_headers
from octop.infra.work.middleware import _log_attempt
from octop.infra.work.tls import runtime_client_ssl_context


def test_runtime_urls_are_derived_from_a_private_base_endpoint() -> None:
    handoff_url, websocket_url = runtime_urls("https://runtime-b.internal:8080", "agent-b")

    assert handoff_url == "https://runtime-b.internal:8080/api/internal/work/handoff"
    assert websocket_url == ("wss://runtime-b.internal:8080/api/agents/agent-b/chat/ws")


def test_runtime_access_token_is_sent_in_a_header_not_the_websocket_url() -> None:
    assert runtime_websocket_headers("runtime-token", "b" * 32) == {
        "Authorization": "Bearer runtime-token",
        "X-Work-Connection-ID": "b" * 32,
    }


def test_forwarded_runtime_connection_accepts_only_bearer_header_token() -> None:
    assert websocket_auth_token("query-secret", "Bearer header-secret", forwarded=True) == (
        "header-secret"
    )
    assert websocket_auth_token("query-secret", None, forwarded=True) is None
    assert websocket_auth_token("browser-secret", None, forwarded=False) == "browser-secret"


def test_browser_websocket_auth_uses_subprotocol_without_a_query_token() -> None:
    assert extract_websocket_auth(
        query_token=None,
        authorization=None,
        protocol_header="octop.chat, octop.auth.header.payload.signature",
        forwarded=False,
    ) == ("header.payload.signature", "octop.chat")


def test_external_attempt_log_carries_connection_run_and_attempt_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = datetime.now(UTC)
    context = ExecutionContext(
        work_user_id="work-user-a",
        organization_id="org-a",
        project_id=None,
        workspace_scope="org-a/user-a",
        run_id="run-a",
        budget_scope_id="thread-a",
        policy_revision=1,
        membership_revision=1,
        allowed_asset_versions=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        connection_id="c" * 32,
        agent_id="agent-a",
        runtime_id="runtime-a",
        octop_user_id=41,
    )

    with caplog.at_level("INFO"):
        _log_attempt("work_external_attempt_started", context, "attempt-a", "model:test")

    record = caplog.records[-1]
    assert record.work_connection_id == "c" * 32
    assert record.work_run_id == "run-a"
    assert record.work_attempt_id == "attempt-a"
    assert record.work_capability == "model:test"


@pytest.mark.asyncio
async def test_existing_dashboard_websocket_route_delegates_in_work_entry_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    async def delegated(_websocket: object, agent_id: str, token: str | None) -> None:
        calls.append((agent_id, token))

    monkeypatch.setattr("octop.api.routers.work_entry.work_entry_chat_ws", delegated)
    server = SimpleNamespace(app_runtime=SimpleNamespace(work_entry_mode=True))
    websocket = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(octop_server=server)),
    )

    await dashboard_chat_ws(websocket, "agent-b", "browser-token")

    assert calls == [("agent-b", "browser-token")]


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://runtime-b.internal",
        "http://runtime-b.internal",
        "http://user:password@runtime-b.internal",
        "http://runtime-b.internal/base",
        "http://runtime-b.internal?target=other",
    ],
)
def test_runtime_endpoint_rejects_ambiguous_or_credentialed_urls(endpoint: str) -> None:
    with pytest.raises(ValueError):
        runtime_urls(endpoint, "agent-b")


def test_runtime_client_tls_fails_closed_without_all_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORK_RUNTIME_MTLS_CA_FILE", "/missing/ca.pem")
    monkeypatch.delenv("WORK_RUNTIME_MTLS_CERT_FILE", raising=False)
    monkeypatch.delenv("WORK_RUNTIME_MTLS_KEY_FILE", raising=False)

    with pytest.raises(RuntimeError, match="mTLS"):
        runtime_client_ssl_context()
