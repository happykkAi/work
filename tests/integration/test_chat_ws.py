"""tests/integration/test_chat_ws.py — dashboard WebSocket chat + thread CRUD."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import ToolException, tool
from starlette.websockets import WebSocketDisconnect
from work_platform.authorization import ExecutionGrant
from work_platform.capability_policy import CapabilityPolicy
from work_platform.runtime_adapter import RuntimeBinding

from octop.infra.work.middleware import WorkExecutionMiddleware
from tests.support.app import octop_client
from tests.support.auth import (
    auth_header,
    bootstrap_admin,
    create_agent,
    ensure_users,
    seed_openai_provider,
)
from tests.support.fakes import FakeHarnessAgent
from tests.support.http import ws_connect


async def test_enqueue_and_block_failure_still_finishes_turn(
    env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, srv, _fake, auth, _bob, aid = env

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(srv.app_runtime.gateway.channel_manager, "enqueue", fail)
    monkeypatch.setattr(srv.app_runtime.work_control_plane, "block_run", fail)
    async with _chat_ws(c, aid, auth) as ws:
        await ws.send_json({"type": "user_turn", "text": "synthetic"})
        assert (await ws.receive_json())["type"] == "error"
        assert (await ws.receive_json())["type"] == "done"


class SyntheticWorkControlPlane:
    """In-memory test directory for real Work authorization code paths."""

    def __init__(self) -> None:
        self.grants: dict[tuple[int, str], ExecutionGrant] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.attempts: dict[str, dict[str, str]] = {}
        self.policies: dict[str, CapabilityPolicy | None] = {}
        self.policy_error = False
        self.budget_available = True

    def bind_member(self, user_id: int, agent_id: str, organization_id: str = "org-a") -> None:
        self.grants[(user_id, agent_id)] = ExecutionGrant(
            octop_user_id=user_id,
            work_user_id=f"work-user-{user_id}",
            organization_id=organization_id,
            agent_id=agent_id,
            member_status="active",
            membership_revision=1,
            policy_revision=1,
            runtime=RuntimeBinding(
                organization_id,
                f"runtime-{organization_id}",
                f"role-{organization_id}",
                f"volume-{organization_id}",
                f"secret-{organization_id}",
            ),
        )
        self.policies.setdefault(
            organization_id,
            CapabilityPolicy(
                enabled=frozenset({"model:openai/test-model", "tool:synthetic_read"}),
                billable=frozenset({"model:openai/test-model", "tool:synthetic_read"}),
            ),
        )

    def revoke_member(self, user_id: int, agent_id: str) -> None:
        grant = self.grants[(user_id, agent_id)]
        self.grants[(user_id, agent_id)] = replace(
            grant,
            member_status="disabled",
            membership_revision=grant.membership_revision + 1,
        )

    def resolve_grant(self, octop_user_id: int, agent_id: str) -> ExecutionGrant | None:
        return self.grants.get((octop_user_id, agent_id))

    def create_run(self, context: Any) -> None:
        self.runs[context.run_id] = {"context": context, "status": "queued"}

    def _grant_matches(self, context: Any) -> bool:
        grant = self.resolve_grant(context.octop_user_id, context.agent_id)
        return bool(
            grant
            and grant.member_status == "active"
            and grant.work_user_id == context.work_user_id
            and grant.organization_id == context.organization_id
            and grant.membership_revision == context.membership_revision
            and grant.policy_revision == context.policy_revision
            and grant.runtime.runtime_id == context.runtime_id
        )

    def activate_run(self, context: Any) -> bool:
        run = self.runs.get(context.run_id)
        if run is None or run["status"] != "queued" or not context.is_current():
            return False
        if not self._grant_matches(context):
            return False
        run["status"] = "running"
        return True

    def block_run(self, context: Any) -> None:
        run = self.runs.get(context.run_id)
        if run is not None and run["status"] in {"queued", "running"}:
            run["status"] = "blocked"

    def finish_run(self, context: Any, status: str) -> None:
        self.runs[context.run_id]["status"] = status

    def context_is_current(self, context: Any) -> bool:
        run = self.runs.get(context.run_id)
        return bool(
            run
            and run["status"] == "running"
            and context.is_current()
            and self._grant_matches(context)
        )

    def load_policy(self, context: Any) -> CapabilityPolicy | None:
        if self.policy_error:
            raise RuntimeError("synthetic policy read failure")
        return self.policies.get(context.organization_id)

    def reserve_attempt(self, context: Any, capability: str, attempt_id: str) -> bool:
        if not self.budget_available or not self.context_is_current(context):
            return False
        if attempt_id in self.attempts:
            return False
        self.attempts[attempt_id] = {"capability": capability, "status": "reserved"}
        return True

    def finish_attempt(self, attempt_id: str, status: str) -> None:
        if attempt_id in self.attempts:
            self.attempts[attempt_id]["status"] = status

    def close(self) -> None:
        pass


@contextmanager
def local_chat_service(
    responses: list[dict[str, Any]],
    *,
    after_request: Any | None = None,
) -> Any:
    """Serve captured OpenAI-compatible completions on loopback only."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
            calls.append((self.path, body))
            if after_request is not None:
                after_request(body)
            if not responses:
                self.send_error(503, "synthetic response exhausted")
                return
            message = responses.pop(0)
            response = {
                "id": "chatcmpl-synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model", "test-model"),
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            payload = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _install_local_graph(
    agent: Any,
    *,
    base_url: str,
    tools: list[Any],
) -> None:
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(model="test-model", base_url=base_url, api_key="synthetic")
    graph = create_agent(model, tools=tools, middleware=[WorkExecutionMiddleware()])

    async def stream(_request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        result = await graph.ainvoke({"messages": [HumanMessage(content="run synthetic task")]})
        yield {"type": "token", "node": "agent", "content": result["messages"][-1].content}

    agent.stream = stream


def _chat_ws(c: httpx.AsyncClient, aid: str, auth: dict[str, str]) -> Any:
    return ws_connect(
        c._octop_app,
        f"/api/agents/{aid}/chat/ws",
        subprotocols=["octop.chat", "octop.auth." + auth["Authorization"].split(" ", 1)[1]],
    )  # type: ignore[attr-defined]


@pytest.fixture
async def env(tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    monkeypatch.delenv("WORK_CONTROL_DATABASE_URL", raising=False)
    monkeypatch.delenv("WORK_RUNTIME_ID", raising=False)
    fake = FakeHarnessAgent(
        chunks=[
            {"type": "token", "node": "agent", "content": "Hello "},
            {"type": "token", "node": "agent", "content": "Bob."},
        ]
    )
    async with octop_client(tmp_octop_home, fake_agent=fake) as (c, srv):
        assert srv.app_runtime is not None
        work_directory = SyntheticWorkControlPlane()
        srv.app_runtime.work_control_plane = work_directory  # type: ignore[assignment]
        srv.app_runtime.work_execution_required = True
        srv.app_runtime.agent_registry._work_control_plane = work_directory
        srv.app_runtime.agent_registry._work_execution_required = True
        await bootstrap_admin(c, tmp_octop_home)
        admin_auth = await auth_header(c)
        await seed_openai_provider(c, admin_auth)
        users = await ensure_users(c, admin_auth, "alice", "bob")
        aid = await create_agent(c, users["alice"])
        agent_row = srv.services.repos.agent_repo.get(aid)
        assert agent_row is not None and agent_row.user_id is not None
        work_directory.bind_member(agent_row.user_id, aid)
        yield c, srv, fake, users["alice"], users["bob"], aid


async def _turn_then_rebind(
    c: httpx.AsyncClient,
    aid: str,
    auth: dict[str, str],
    thread_id: str,
    gate_release: asyncio.Event,
) -> list[dict[str, Any]]:
    """Start a turn on conn A, drop it after the first token, re-subscribe on B.

    The fake stream is gated between first and second token so B can subscribe
    while the turn is still active, then receive the remaining chunks.
    """
    async with _chat_ws(c, aid, auth) as ws_a:
        await ws_a.send_json(
            {
                "type": "user_turn",
                "text": "slow please",
                "thread_id": thread_id,
            }
        )
        first = await ws_a.receive_json()
        assert first.get("type") == "token"
        assert first.get("content") == "first"
    # A is closed; turn is blocked on gate_release (still active, not cancelled).

    frames: list[dict[str, Any]] = []
    async with _chat_ws(c, aid, auth) as ws_b:
        await ws_b.send_json({"type": "subscribe", "thread_id": thread_id})
        frames.append(await ws_b.receive_json())
        # Release the slow stream only after B is subscribed.
        gate_release.set()
        frames.extend(await ws_b.drain_turn())
    return frames


async def test_ws_rebind_after_disconnect_receives_later_chunks(env: Any) -> None:
    """After disconnect, a new subscriber must see subsequent tokens + done."""
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    create = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    tid = create.json()["thread_id"]
    agent = srv.app_runtime.agent_registry.get_agent(aid)

    gate = asyncio.Event()

    async def slow_stream(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "token", "node": "agent", "content": "first"}
        await gate.wait()
        yield {"type": "token", "node": "agent", "content": "second"}

    agent.stream = slow_stream
    cancel_spy = MagicMock(wraps=srv.app_runtime.agent_registry.cancel_stream)
    srv.app_runtime.agent_registry.cancel_stream = cancel_spy

    frames = await _turn_then_rebind(c, aid, alice_auth, tid, gate)

    cancel_spy.assert_not_called()
    assert frames[0] == {"type": "turn_status", "thread_id": tid, "active": True}
    contents = [f.get("content") for f in frames if f.get("type") == "token"]
    assert "second" in contents
    assert frames[-1].get("type") == "done"


async def _turn_with_second_subscriber(
    c: httpx.AsyncClient,
    aid: str,
    auth: dict[str, str],
    thread_id: str,
    gate_release: asyncio.Event,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep conn A open, subscribe conn B mid-turn; both receive remaining chunks."""
    a_frames: list[dict[str, Any]] = []
    b_frames: list[dict[str, Any]] = []
    async with _chat_ws(c, aid, auth) as ws_a:
        await ws_a.send_json(
            {
                "type": "user_turn",
                "text": "slow please",
                "thread_id": thread_id,
            }
        )
        a_frames.append(await ws_a.receive_json())
        async with _chat_ws(c, aid, auth) as ws_b:
            await ws_b.send_json({"type": "subscribe", "thread_id": thread_id})
            b_frames.append(await ws_b.receive_json())
            gate_release.set()
            rest_a, rest_b = await asyncio.gather(ws_a.drain_turn(), ws_b.drain_turn())
            a_frames.extend(rest_a)
            b_frames.extend(rest_b)
    return a_frames, b_frames


async def _two_threads_turn(
    c: httpx.AsyncClient,
    aid: str,
    auth: dict[str, str],
    tid_a: str,
    tid_b: str,
    *,
    text_a: str = "one",
    text_b: str = "two",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run two live turns on different threads over two concurrent sockets."""
    body_a: dict[str, Any] = {
        "type": "user_turn",
        "text": text_a,
        "messages": [{"role": "user", "content": text_a}],
        "thread_id": tid_a,
    }
    body_b: dict[str, Any] = {
        "type": "user_turn",
        "text": text_b,
        "messages": [{"role": "user", "content": text_b}],
        "thread_id": tid_b,
    }
    async with _chat_ws(c, aid, auth) as ws_a, _chat_ws(c, aid, auth) as ws_b:
        await ws_a.send_json(body_a)
        await ws_b.send_json(body_b)
        return await asyncio.gather(ws_a.drain_turn(), ws_b.drain_turn())  # type: ignore[return-value]


async def test_ws_concurrent_subscribers_both_receive_later_chunks(env: Any) -> None:
    """Two dashboard sockets on the same thread both get live tokens."""
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    create = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    tid = create.json()["thread_id"]
    agent = srv.app_runtime.agent_registry.get_agent(aid)

    gate = asyncio.Event()

    async def slow_stream(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "token", "node": "agent", "content": "first"}
        await gate.wait()
        yield {"type": "token", "node": "agent", "content": "second"}

    agent.stream = slow_stream

    a_frames, b_frames = await _turn_with_second_subscriber(c, aid, alice_auth, tid, gate)

    assert a_frames[0].get("content") == "first"
    assert [f.get("content") for f in a_frames if f.get("type") == "token"] == ["first", "second"]
    assert a_frames[-1].get("type") == "done"
    assert b_frames[0] == {"type": "turn_status", "thread_id": tid, "active": True}
    assert [f.get("content") for f in b_frames if f.get("type") == "token"] == ["second"]
    assert b_frames[-1].get("type") == "done"


async def test_ws_two_threads_do_not_cross_stream(env: Any) -> None:
    """Two live turns on different threads must not mix tokens across sockets."""
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    create_a = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    create_b = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    tid_a = create_a.json()["thread_id"]
    tid_b = create_b.json()["thread_id"]
    agent = srv.app_runtime.agent_registry.get_agent(aid)

    async def tagged_stream(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        tid = str(request.get("thread_id") or "")
        yield {"type": "token", "node": "agent", "content": f"from-{tid}"}

    agent.stream = tagged_stream

    a_frames, b_frames = await _two_threads_turn(c, aid, alice_auth, tid_a, tid_b)

    a_tokens = [f.get("content") for f in a_frames if f.get("type") == "token"]
    b_tokens = [f.get("content") for f in b_frames if f.get("type") == "token"]
    assert a_tokens == [f"from-{tid_a}"]
    assert b_tokens == [f"from-{tid_b}"]
    assert all(f.get("thread_id") == tid_a for f in a_frames if f.get("type") in ("token", "done"))
    assert all(f.get("thread_id") == tid_b for f in b_frames if f.get("type") in ("token", "done"))


async def _consume_ws_turn(
    c: httpx.AsyncClient,
    aid: str,
    auth: dict[str, str],
    *,
    text: str = "Hello",
    thread_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "type": "user_turn",
        "text": text,
        "messages": [{"role": "user", "content": text}],
    }
    if thread_id:
        body["thread_id"] = thread_id
    if extra:
        body.update(extra)

    async with _chat_ws(c, aid, auth) as ws:
        await ws.send_json(body)
        return await ws.drain_turn()


async def test_ws_emits_chunks_then_done(env: Any) -> None:
    c, _srv, _fake, alice_auth, _bob_auth, aid = env
    chunks = await _consume_ws_turn(c, aid, alice_auth)
    await asyncio.sleep(0.05)
    types = [ch.get("type") for ch in chunks]
    assert "token" in types
    assert chunks[-1]["type"] == "done"


async def test_ws_work_mode_without_control_plane_rejects_connection(env: Any) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    srv.app_runtime.work_control_plane = None
    srv.app_runtime.agent_registry._work_control_plane = None

    with pytest.raises(WebSocketDisconnect) as exc_info:
        async with _chat_ws(c, aid, alice_auth):
            pytest.fail("Work chat must close before accepting a connection")

    assert exc_info.value.code == 4003


async def test_work_runtime_blocks_proactive_ai_scheduling(
    tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WORK_CONTROL_DATABASE_URL", raising=False)
    monkeypatch.setenv("WORK_RUNTIME_ID", "synthetic-runtime")

    async with octop_client(tmp_octop_home) as (c, server):
        assert server.app_runtime is not None
        assert server.app_runtime.work_execution_required is True
        await bootstrap_admin(c, tmp_octop_home)
        admin_auth = await auth_header(c)
        users = await ensure_users(c, admin_auth, "alice", "bob")
        aid = await create_agent(c, users["alice"])

        config_repo = server.services.repos.proactive_care_config_repo
        upsert = MagicMock(wraps=config_repo.upsert)
        monkeypatch.setattr(config_repo, "upsert", upsert)
        response = await c.put(
            f"/api/agents/{aid}/proactive-care",
            headers=users["alice"],
            json={"enabled": True},
        )

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FORBIDDEN"
        upsert.assert_not_called()
        assert aid not in server.app_runtime.proactive_scheduler._tasks


def _tool_message(name: str, call_id: str, *, value: str = "synthetic") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({"value": value})},
            }
        ],
    }


def _text_message(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


async def test_ws_allowed_member_reaches_local_model_and_tool(env: Any) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    directory = srv.app_runtime.work_control_plane
    reads: list[str] = []

    @tool
    def synthetic_read(value: str) -> str:
        """Read a synthetic local resource."""
        reads.append(value)
        return f"local:{value}"

    with local_chat_service(
        [_tool_message("synthetic_read", "read-1"), _text_message("任务完成")]
    ) as (base_url, requests):
        agent = srv.app_runtime.agent_registry.get_agent(aid)
        _install_local_graph(agent, base_url=base_url, tools=[synthetic_read])
        frames = await _consume_ws_turn(c, aid, alice_auth)

    assert len(requests) == 2
    assert all(path.endswith("/chat/completions") for path, _body in requests)
    assert all(body["model"] == "test-model" for _path, body in requests)
    assert reads == ["synthetic"]
    assert [entry["capability"] for entry in directory.attempts.values()] == [
        "model:openai/test-model",
        "tool:synthetic_read",
        "model:openai/test-model",
    ]
    assert {entry["status"] for entry in directory.attempts.values()} == {"completed"}
    assert next(iter(directory.runs.values()))["status"] == "completed"

    create_call = srv.app_runtime.agent_registry.harness_manager.acreate_agent.call_args
    assert create_call is not None
    runtime_config = create_call.args[0]
    assert any(isinstance(item, WorkExecutionMiddleware) for item in runtime_config.middleware)
    assert any(frame.get("content") == "任务完成" for frame in frames)


async def test_ws_cannot_read_another_organizations_synthetic_resource(env: Any) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    directory = srv.app_runtime.work_control_plane
    directory.policies["org-a"] = CapabilityPolicy(
        enabled=frozenset({"model:openai/test-model"}),
        billable=frozenset({"model:openai/test-model"}),
    )
    reads_from_b: list[str] = []

    @tool
    def read_org_b(value: str) -> str:
        """Read a synthetic resource owned by organization B."""
        reads_from_b.append(value)
        return value

    with local_chat_service([_tool_message("read_org_b", "org-b-read")]) as (
        base_url,
        requests,
    ):
        agent = srv.app_runtime.agent_registry.get_agent(aid)
        _install_local_graph(agent, base_url=base_url, tools=[read_org_b])
        frames = await _consume_ws_turn(c, aid, alice_auth)

    assert len(requests) == 1
    assert reads_from_b == []
    assert [entry["capability"] for entry in directory.attempts.values()] == [
        "model:openai/test-model"
    ]
    assert next(iter(directory.runs.values()))["status"] == "blocked"
    assert any(frame.get("type") == "error" for frame in frames)


async def test_ws_revocation_during_model_call_blocks_next_tool_step(env: Any) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    directory = srv.app_runtime.work_control_plane
    agent_row = srv.services.repos.agent_repo.get(aid)
    assert agent_row is not None and agent_row.user_id is not None
    writes: list[str] = []

    @tool
    def synthetic_write(value: str) -> str:
        """Write to a synthetic local resource."""
        writes.append(value)
        return "written"

    def revoke_after_model_receives_request(_body: dict[str, Any]) -> None:
        directory.revoke_member(agent_row.user_id, aid)

    with local_chat_service(
        [_tool_message("synthetic_write", "write-after-revoke")],
        after_request=revoke_after_model_receives_request,
    ) as (base_url, requests):
        agent = srv.app_runtime.agent_registry.get_agent(aid)
        _install_local_graph(agent, base_url=base_url, tools=[synthetic_write])
        frames = await _consume_ws_turn(c, aid, alice_auth)

    assert len(requests) == 1
    assert writes == []
    assert [entry["capability"] for entry in directory.attempts.values()] == [
        "model:openai/test-model"
    ]
    assert next(iter(directory.runs.values()))["status"] == "blocked"
    assert any(frame.get("type") == "error" for frame in frames)


@pytest.mark.parametrize("failure", ["policy", "budget"])
async def test_ws_policy_or_budget_failure_sends_no_model_request(env: Any, failure: str) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    directory = srv.app_runtime.work_control_plane
    if failure == "policy":
        directory.policy_error = True
    else:
        directory.budget_available = False

    with local_chat_service([_text_message("must not run")]) as (base_url, requests):
        agent = srv.app_runtime.agent_registry.get_agent(aid)
        _install_local_graph(agent, base_url=base_url, tools=[])
        frames = await _consume_ws_turn(c, aid, alice_auth)

    assert requests == []
    assert directory.attempts == {}
    assert next(iter(directory.runs.values()))["status"] == "blocked"
    assert any(frame.get("type") == "error" for frame in frames)


async def test_ws_uncertain_tool_write_is_not_retried(env: Any) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    directory = srv.app_runtime.work_control_plane
    directory.policies["org-a"] = CapabilityPolicy(
        enabled=frozenset({"model:openai/test-model", "tool:synthetic_write"}),
        billable=frozenset({"model:openai/test-model", "tool:synthetic_write"}),
    )
    writes: list[str] = []

    @tool
    def synthetic_write(value: str) -> str:
        """Write to a synthetic local resource that times out after sending."""
        writes.append(value)
        raise ToolException("synthetic write result is uncertain")

    with local_chat_service([_tool_message("synthetic_write", "uncertain-write-1")]) as (
        base_url,
        requests,
    ):
        agent = srv.app_runtime.agent_registry.get_agent(aid)
        _install_local_graph(agent, base_url=base_url, tools=[synthetic_write])
        frames = await _consume_ws_turn(c, aid, alice_auth)

    assert writes == ["synthetic"]
    assert len(requests) == 1
    tool_attempts = [
        entry
        for entry in directory.attempts.values()
        if entry["capability"] == "tool:synthetic_write"
    ]
    assert len(tool_attempts) == 1
    assert tool_attempts[0]["status"] == "uncertain"
    assert not any(frame.get("content") == "写入成功" for frame in frames)


async def test_ws_disconnect_does_not_cancel_active_turn(env: Any) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    agent = srv.app_runtime.agent_registry.get_agent(aid)

    async def slow_stream(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "token", "node": "agent", "content": "started"}
        await asyncio.sleep(1)

    agent.stream = slow_stream
    original_cancel = srv.app_runtime.agent_registry.cancel_stream
    cancel_spy = MagicMock(wraps=original_cancel)
    srv.app_runtime.agent_registry.cancel_stream = cancel_spy

    async with _chat_ws(c, aid, alice_auth) as ws:
        await ws.send_json({"type": "user_turn", "text": "cancel me"})
        await ws.receive_json()

    await asyncio.sleep(0.05)
    cancel_spy.assert_not_called()


async def _subscribe_ws(
    c: httpx.AsyncClient,
    aid: str,
    auth: dict[str, str],
    thread_id: str,
) -> dict[str, Any]:
    async with _chat_ws(c, aid, auth) as ws:
        await ws.send_json({"type": "subscribe", "thread_id": thread_id})
        return await ws.receive_json()


async def test_ws_subscribe_turn_status_idle(env: Any) -> None:
    c, _srv, _fake, alice_auth, _bob_auth, aid = env
    create = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    assert create.status_code == 201
    tid = create.json()["thread_id"]

    frame = await _subscribe_ws(c, aid, alice_auth, tid)
    assert frame == {"type": "turn_status", "thread_id": tid, "active": False}


async def test_ws_subscribe_rejects_another_users_thread(env: Any) -> None:
    c, _srv, _fake, alice_auth, bob_auth, aid = env
    response = await c.patch(
        f"/api/agents/{aid}",
        headers=alice_auth,
        json={"is_shared": True},
    )
    assert response.status_code == 200, response.text

    response = await c.post(f"/api/agents/{aid}/threads", headers=bob_auth)
    assert response.status_code == 201, response.text
    tid = response.json()["thread_id"]

    frame = await _subscribe_ws(c, aid, alice_auth, tid)
    assert frame == {"type": "error", "message": f"thread {tid!r} not found"}


async def test_ws_cancel_frame_cancels_active_turn(env: Any) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    agent = srv.app_runtime.agent_registry.get_agent(aid)
    create = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    tid = create.json()["thread_id"]

    async def slow_stream(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "token", "node": "agent", "content": "started"}
        await asyncio.sleep(1)

    agent.stream = slow_stream
    original_cancel = srv.app_runtime.agent_registry.cancel_stream
    cancel_spy = MagicMock(wraps=original_cancel)
    srv.app_runtime.agent_registry.cancel_stream = cancel_spy

    async with _chat_ws(c, aid, alice_auth) as ws:
        await ws.send_json({"type": "user_turn", "text": "cancel me", "thread_id": tid})
        await ws.receive_json()  # first token
        await ws.send_json({"type": "cancel", "thread_id": tid})

    for _ in range(40):
        if cancel_spy.called:
            break
        await asyncio.sleep(0.01)
    cancel_spy.assert_called()
    assert cancel_spy.call_args.args[0] == aid
    assert cancel_spy.call_args.args[1] == tid


async def test_ws_emits_error_frame_on_exception(env: Any) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    agent = srv.app_runtime.agent_registry.get_agent(aid)
    agent.raise_on_stream = RuntimeError("upstream blew up")

    chunks = await _consume_ws_turn(c, aid, alice_auth, text="err")
    assert chunks[-1]["type"] == "error"


async def test_ws_bad_agent_rejected(env: Any) -> None:
    c, _srv, _fake, alice_auth, _bob_auth, _aid = env
    with pytest.raises(WebSocketDisconnect):
        async with _chat_ws(c, "01HMISSING0000000000000000", alice_auth):
            pass


async def test_ws_cross_user_rejected(env: Any) -> None:
    c, _srv, _fake, _admin_auth, bob_auth, aid = env
    with pytest.raises(WebSocketDisconnect):
        async with _chat_ws(c, aid, bob_auth):
            pass


async def test_ws_accepts_skills_and_model(env: Any) -> None:
    c, _srv, _fake, auth, _bob_auth, aid = env
    chunks = await _consume_ws_turn(
        c,
        aid,
        auth,
        extra={"skills": [], "model": "openai/gpt-4o"},
    )
    assert chunks[-1]["type"] == "done"


async def test_polish_rejects_empty_text(env: Any) -> None:
    c, _srv, _fake, alice_auth, _bob_auth, aid = env
    r = await c.post(
        f"/api/agents/{aid}/chat/polish",
        headers=alice_auth,
        json={"text": "   "},
    )
    assert r.status_code == 400


async def test_polish_is_disabled_in_work_mode_before_model_call(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    harness = MagicMock()
    harness.config.pick_default_model_ref.return_value = "openai/test-model"
    get_model = harness.model_factory.get
    monkeypatch.setattr(
        srv.app_runtime.agent_registry,
        "get_agent",
        MagicMock(return_value=harness),
    )
    invoke = AsyncMock(return_value="rewritten")
    monkeypatch.setattr("octop.api.routers.chat.routes.ainvoke_text", invoke)

    response = await c.post(
        f"/api/agents/{aid}/chat/polish",
        headers=alice_auth,
        json={"text": "synthetic private notes"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"
    get_model.assert_not_called()
    invoke.assert_not_awaited()


async def test_threads_list_after_stream(env: Any) -> None:
    c, _srv, _fake, alice_auth, _bob_auth, aid = env
    await _consume_ws_turn(c, aid, alice_auth, text="What's up?")
    await asyncio.sleep(0.05)

    r = await c.get(f"/api/agents/{aid}/threads", headers=alice_auth)
    assert r.status_code == 200
    threads = r.json()
    assert len(threads) >= 1
    assert any(t.get("has_messages") for t in threads)


async def test_thread_history_after_stream(env: Any) -> None:
    c, _srv, _fake, alice_auth, _bob_auth, aid = env
    await _consume_ws_turn(c, aid, alice_auth, text="History test")
    await asyncio.sleep(0.05)

    r = await c.get(f"/api/agents/{aid}/threads", headers=alice_auth)
    tid = r.json()[0]["thread_id"]
    hist = await c.get(f"/api/agents/{aid}/threads/{tid}/history", headers=alice_auth)
    assert hist.status_code == 200
    assert "messages" in hist.json()


async def test_thread_history_reports_active_turn(env: Any) -> None:
    """History must expose whether a turn is still running, so a reloaded
    dashboard can re-subscribe instead of guessing from the message list."""
    c, srv, _fake, alice_auth, _bob_auth, aid = env
    create = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    tid = create.json()["thread_id"]

    idle = await c.get(f"/api/agents/{aid}/threads/{tid}/history", headers=alice_auth)
    assert idle.json()["turn_active"] is False

    srv.app_runtime.gateway.ws_hub.mark_turn_active(tid)
    active = await c.get(f"/api/agents/{aid}/threads/{tid}/history", headers=alice_auth)
    assert active.json()["turn_active"] is True


async def test_create_thread(env: Any) -> None:
    c, _srv, _fake, alice_auth, _bob_auth, aid = env
    r = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    assert r.status_code == 201
    body = r.json()
    assert "thread_id" in body
    assert "session_key" in body


async def test_fork_thread_from_assistant_message(env: Any) -> None:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    c, srv, _fake, alice_auth, bob_auth, aid = env
    created = await c.post(f"/api/agents/{aid}/threads", headers=alice_auth)
    source_id = created.json()["thread_id"]
    agent = srv.app_runtime.agent_registry.get_agent(aid)
    agent.seed_thread_messages(
        source_id,
        [
            HumanMessage(content="first question", id="h1"),
            AIMessage(content="first answer", id="a1"),
            ToolMessage(content="tool-out", id="t1", tool_call_id="c1"),
            HumanMessage(content="second question", id="h2"),
            AIMessage(content="second answer", id="a2"),
        ],
    )

    forked = await c.post(
        f"/api/agents/{aid}/threads/{source_id}/fork",
        headers=alice_auth,
        json={
            "message_id": "a1",
            "content": "first answer",
            "assistant_turns_from_end": 2,
        },
    )
    assert forked.status_code == 201, forked.text
    body = forked.json()
    dest_id = body["thread_id"]
    assert dest_id != source_id
    assert body["source_thread_id"] == source_id
    assert body["copied_messages"] == 2

    history = await c.get(
        f"/api/agents/{aid}/threads/{dest_id}/history",
        headers=alice_auth,
    )
    assert history.status_code == 200
    roles = [m["role"] for m in history.json()["messages"]]
    texts = []
    for msg in history.json()["messages"]:
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(str(block.get("text") or ""))
                elif isinstance(block, dict) and block.get("type") == "tool_result":
                    texts.append(str(block.get("output") or ""))
    assert "user" in roles
    assert "assistant" in roles
    assert "first question" in texts
    assert "first answer" in texts
    assert "second question" not in texts
    assert "second answer" not in texts

    source_history = await c.get(
        f"/api/agents/{aid}/threads/{source_id}/history",
        headers=alice_auth,
    )
    source_texts: list[str] = []
    for msg in source_history.json()["messages"]:
        content = msg.get("content")
        if isinstance(content, str):
            source_texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    source_texts.append(str(block.get("text") or ""))
    assert "first question" in source_texts
    assert "second question" in source_texts

    denied = await c.post(
        f"/api/agents/{aid}/threads/{source_id}/fork",
        headers=bob_auth,
        json={"message_id": "a1", "assistant_turns_from_end": 2},
    )
    assert denied.status_code in {403, 404}
