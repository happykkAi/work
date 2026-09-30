from __future__ import annotations

import asyncio
import datetime
import ipaddress
import socket
import ssl
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import FastAPI, Header, WebSocket
from websockets.asyncio.client import connect
from work_platform.authorization import ExecutionGrant
from work_platform.runtime_adapter import RuntimeBinding

from octop.api.routers.chat.ws import router as dashboard_chat_router
from octop.api.routers.work_entry import router as work_entry_router
from octop.infra.work.routing import exchange_runtime_handoff


class Directory:
    expected_runtime_binding = None

    def __init__(self, grant: ExecutionGrant) -> None:
        self.grant = grant
        self.consumed: set[str] = set()

    def resolve_entry_grant(self, octop_user_id: int, agent_id: str) -> ExecutionGrant | None:
        return self.grant if (octop_user_id, agent_id) == (7, self.grant.agent_id) else None

    def resolve_runtime_grant(self, work_user_id: str, agent_id: str) -> ExecutionGrant | None:
        return (
            self.grant
            if (work_user_id, agent_id)
            == (
                self.grant.work_user_id,
                self.grant.agent_id,
            )
            else None
        )

    def consume_runtime_handoff(self, handoff: object) -> ExecutionGrant | None:
        handoff_id = str(handoff.handoff_id)
        if handoff_id in self.consumed:
            return None
        self.consumed.add(handoff_id)
        return self.resolve_runtime_grant(str(handoff.work_user_id), str(handoff.agent_id))


def _grant(binding: RuntimeBinding) -> ExecutionGrant:
    return ExecutionGrant(
        octop_user_id=42,
        work_user_id=f"user-{binding.organization_id}",
        organization_id=binding.organization_id,
        agent_id=f"agent-{binding.organization_id}",
        member_status="active",
        membership_revision=1,
        policy_revision=1,
        runtime=binding,
    )


def _runtime_app(binding: RuntimeBinding, secret: bytes, calls: list[str]) -> FastAPI:
    app = FastAPI()
    directory = Directory(_grant(binding))

    @app.post("/api/internal/work/handoff")
    async def handoff(
        payload: dict[str, str], connection_id: str = Header(alias="X-Work-Connection-ID")
    ) -> dict[str, str]:
        grant = exchange_runtime_handoff(
            directory,
            binding,
            secret,
            payload["token"],
            connection_id=connection_id,
        )
        calls.append(f"handoff:{binding.runtime_id}")
        return {
            "access_token": f"local-{grant.octop_user_id}",
            "connection_id": connection_id,
            "runtime_id": binding.runtime_id,
        }

    @app.websocket("/api/agents/{agent_id}/chat/ws")
    async def chat(websocket: WebSocket, agent_id: str) -> None:
        assert agent_id == directory.grant.agent_id
        assert websocket.url.query == ""
        assert websocket.headers["Authorization"] == "Bearer local-42"
        assert len(websocket.headers["X-Work-Connection-ID"]) == 32
        calls.append(f"websocket:{binding.runtime_id}")
        await websocket.accept()
        message = await websocket.receive_text()
        await websocket.send_text(f"{binding.runtime_id}:{message}")
        await websocket.close()

    return app


@asynccontextmanager
async def _serve(
    app_factory: Callable[[int], FastAPI],
    *,
    cert_file: Path,
    key_file: Path,
    ca_file: Path,
) -> AsyncIterator[int]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = int(sock.getsockname()[1])
    app = app_factory(port)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_level="warning",
            lifespan="off",
            access_log=False,
            ssl_certfile=str(cert_file),
            ssl_keyfile=str(key_file),
            ssl_ca_certs=str(ca_file),
            ssl_cert_reqs=ssl.CERT_REQUIRED,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield port
    finally:
        server.should_exit = True
        await task


@asynccontextmanager
async def _serve_plain(app: FastAPI) -> AsyncIterator[int]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = int(sock.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="warning", lifespan="off", access_log=False)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield port
    finally:
        server.should_exit = True
        await task


def _certificates(directory: Path) -> tuple[Path, Path, Path, Path, Path]:
    now = datetime.datetime.now(datetime.UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Work test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    def leaf(name: str, usage: ExtendedKeyUsageOID) -> tuple[Path, Path]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
            .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        cert_path = directory / f"{name}.pem"
        key_path = directory / f"{name}-key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        return cert_path, key_path

    ca_path = directory / "ca.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    server_cert, server_key = leaf("runtime", ExtendedKeyUsageOID.SERVER_AUTH)
    client_cert, client_key = leaf("entry", ExtendedKeyUsageOID.CLIENT_AUTH)
    return ca_path, server_cert, server_key, client_cert, client_key


@pytest.mark.asyncio
async def test_trusted_entry_routes_to_b_without_contacting_a(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_a = b"runtime-a-secret-runtime-a-secret-00"
    secret_b = b"runtime-b-secret-runtime-b-secret-00"
    (tmp_path / "handoff-a").write_bytes(secret_a)
    (tmp_path / "handoff-b").write_bytes(secret_b)
    calls: list[str] = []
    ca_file, server_cert, server_key, client_cert, client_key = _certificates(tmp_path)
    monkeypatch.setenv("WORK_RUNTIME_MTLS_CA_FILE", str(ca_file))
    monkeypatch.setenv("WORK_RUNTIME_MTLS_CERT_FILE", str(client_cert))
    monkeypatch.setenv("WORK_RUNTIME_MTLS_KEY_FILE", str(client_key))
    monkeypatch.setenv("WORK_RUNTIME_SECRETS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "octop.api.routers.work_entry.resolve_user_from_token",
        lambda _server, token: SimpleNamespace(id=7) if token == "browser-token" else None,
    )

    def runtime_a(port: int) -> FastAPI:
        return _runtime_app(
            RuntimeBinding(
                "org-a",
                "runtime-a",
                "role-a",
                "volume-a",
                "database-a",
                f"https://127.0.0.1:{port}",
                "handoff-a",
            ),
            secret_a,
            calls,
        )

    def runtime_b(port: int) -> FastAPI:
        return _runtime_app(
            RuntimeBinding(
                "org-b",
                "runtime-b",
                "role-b",
                "volume-b",
                "database-b",
                f"https://127.0.0.1:{port}",
                "handoff-b",
            ),
            secret_b,
            calls,
        )

    async with (
        _serve(runtime_a, cert_file=server_cert, key_file=server_key, ca_file=ca_file),
        _serve(
            runtime_b, cert_file=server_cert, key_file=server_key, ca_file=ca_file
        ) as runtime_b_port,
    ):
        binding_b = RuntimeBinding(
            "org-b",
            "runtime-b",
            "role-b",
            "volume-b",
            "database-b",
            f"https://127.0.0.1:{runtime_b_port}",
            "handoff-b",
        )
        directory = Directory(_grant(binding_b))
        entry = FastAPI()
        entry.include_router(work_entry_router, prefix="/api")
        entry.include_router(dashboard_chat_router, prefix="/api")
        entry.state.octop_server = SimpleNamespace(
            app_runtime=SimpleNamespace(
                work_control_plane=directory,
                work_entry_mode=True,
            )
        )
        async with (
            _serve_plain(entry) as entry_port,
            connect(
                f"ws://127.0.0.1:{entry_port}/api/agents/agent-org-b/chat/ws",
                subprotocols=["octop.chat", "octop.auth.browser-token"],
                proxy=None,
            ) as websocket,
        ):
            assert websocket.subprotocol == "octop.chat"
            await websocket.send("hello")
            assert await websocket.recv() == "runtime-b:hello"

    assert calls == ["handoff:runtime-b", "websocket:runtime-b"]


@pytest.mark.asyncio
async def test_runtime_tls_rejects_a_client_without_a_certificate(tmp_path: Path) -> None:
    ca_file, server_cert, server_key, _client_cert, _client_key = _certificates(tmp_path)
    binding = RuntimeBinding(
        "org-b",
        "runtime-b",
        "role-b",
        "volume-b",
        "database-b",
        "https://unused",
        "handoff-b",
    )
    async with _serve(
        lambda _port: _runtime_app(binding, b"runtime-b-secret-runtime-b-secret-00", []),
        cert_file=server_cert,
        key_file=server_key,
        ca_file=ca_file,
    ) as port:
        with pytest.raises(httpx.HTTPError):
            context = ssl.create_default_context(cafile=ca_file)
            async with httpx.AsyncClient(verify=context, trust_env=False) as client:
                await client.post(f"https://127.0.0.1:{port}/api/internal/work/handoff", json={})


@pytest.mark.asyncio
async def test_runtime_tls_rejects_untrusted_client_and_server_certificates(
    tmp_path: Path,
) -> None:
    trusted = tmp_path / "trusted"
    untrusted = tmp_path / "untrusted"
    trusted.mkdir()
    untrusted.mkdir()
    ca_file, server_cert, server_key, client_cert, client_key = _certificates(trusted)
    other_ca, _other_server, _other_server_key, other_client, other_client_key = _certificates(
        untrusted
    )
    binding = RuntimeBinding(
        "org-b",
        "runtime-b",
        "role-b",
        "volume-b",
        "database-b",
        "https://unused",
        "handoff-b",
    )
    async with _serve(
        lambda _port: _runtime_app(binding, b"runtime-b-secret-runtime-b-secret-00", []),
        cert_file=server_cert,
        key_file=server_key,
        ca_file=ca_file,
    ) as port:
        untrusted_client = ssl.create_default_context(cafile=ca_file)
        untrusted_client.load_cert_chain(other_client, other_client_key)
        wrong_server_ca = ssl.create_default_context(cafile=other_ca)
        wrong_server_ca.load_cert_chain(client_cert, client_key)
        for context in (untrusted_client, wrong_server_ca):
            with pytest.raises(httpx.HTTPError):
                async with httpx.AsyncClient(verify=context, trust_env=False) as client:
                    await client.post(
                        f"https://127.0.0.1:{port}/api/internal/work/handoff", json={}
                    )
