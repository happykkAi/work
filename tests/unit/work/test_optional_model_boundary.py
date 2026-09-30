"""Optional non-Harness models must not bypass Work authorization and budgets."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.knowledge import embed, gate, jobs, ocr
from octop.infra.voice import adapters
from octop.infra.voice.manager import VoiceManager


@pytest.fixture(params=["WORK_ENTRY_MODE", "WORK_RUNTIME_ID", "WORK_CONTROL_DATABASE_URL"])
def work_mode(request, monkeypatch):
    for key in ("WORK_ENTRY_MODE", "WORK_RUNTIME_ID", "WORK_CONTROL_DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(request.param, "true" if request.param == "WORK_ENTRY_MODE" else "synthetic")


def test_work_remote_embedding_cannot_send_document(work_mode, monkeypatch):
    sent = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, url, **kwargs):
            sent.append(url)
            return SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {"data": [{"embedding": [1.0]}]}
            )

    monkeypatch.setattr(embed.httpx, "Client", lambda **_kwargs: Client())
    values = {
        "knowledge_embedding_backend": "remote",
        "knowledge_embedding_model": "embed",
        "knowledge_embedding_provider_id": "1",
    }
    services = SimpleNamespace(
        settings_repo=SimpleNamespace(get=values.get),
        provider_repo=SimpleNamespace(
            get=lambda _id: SimpleNamespace(base_url="https://synthetic.invalid", api_key="test")
        ),
    )
    with pytest.raises(OctopError) as exc:
        embed.embed_knowledge_texts(services, ["synthetic document"])
    assert exc.value.code == ErrorCode.FORBIDDEN
    assert sent == []


def test_work_remote_ocr_cannot_send_image(work_mode, monkeypatch, tmp_path: Path):
    sent = []

    def invoke(messages):
        sent.extend(messages)
        return SimpleNamespace(content="synthetic OCR")

    monkeypatch.setattr(
        ocr, "build_probe_chat_model", lambda *_a, **_kw: SimpleNamespace(invoke=invoke)
    )
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic image")
    with pytest.raises(OctopError) as exc:
        ocr._RemoteOcr(SimpleNamespace(), "vision")(image)
    assert exc.value.code == ErrorCode.FORBIDDEN
    assert sent == []


def test_work_restart_preserves_pending_remote_index_jobs(work_mode):
    values = {"knowledge_embedding_backend": "remote"}
    updates = []
    services = SimpleNamespace(
        settings_repo=SimpleNamespace(get=values.get),
        knowledge_repo=SimpleNamespace(
            resume_pending_documents=lambda: updates.append("reset") or []
        ),
    )
    jobs.resume_pending_index_jobs(services)
    assert updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["stt", "tts", "probe", "draft_probe"])
async def test_work_voice_cannot_bypass_budget(work_mode, operation, monkeypatch):
    sent = []

    async def stt(*_args, **_kwargs):
        sent.append("stt")
        return SimpleNamespace(text="synthetic", confidence=None)

    async def tts(*_args, **_kwargs):
        sent.append("tts")
        yield b"synthetic"

    async def probe(*_args, **_kwargs):
        sent.append("probe")
        return {"ok": True}

    monkeypatch.setattr(adapters, "transcribe_openai", stt)
    monkeypatch.setattr(adapters, "synthesize_openai", tts)
    monkeypatch.setattr(adapters, "test_stt", probe)
    provider = SimpleNamespace(name="cloud", kind="openai", enabled=True)
    manager = VoiceManager(
        settings_repo=SimpleNamespace(get=lambda _key: "cloud"),
        voice_provider_repo=SimpleNamespace(
            get_by_name=lambda _name: provider, get=lambda _id: provider
        ),
    )
    with pytest.raises(OctopError) as exc:
        if operation == "stt":
            await manager.transcribe(b"synthetic", mime="audio/webm")
        elif operation == "tts":
            assert [chunk async for chunk in manager.synthesize("synthetic")] == []
        elif operation == "probe":
            await manager.test_provider(1, mode="stt")
        else:
            await manager.test_configuration(
                name="cloud",
                kind="openai",
                capability="both",
                base_url=None,
                api_key=None,
                extra_json=None,
                mode="stt",
            )
    assert exc.value.code == ErrorCode.FORBIDDEN
    assert sent == []


def test_work_keeps_local_embedding(work_mode, monkeypatch):
    monkeypatch.setattr(embed, "embed_texts", lambda _model, texts: [[1.0] for _ in texts])
    services = SimpleNamespace(settings_repo=SimpleNamespace(get=lambda _key: None))
    assert embed.embed_knowledge_texts(services, ["local document"]) == [[1.0]]


def test_remote_ocr_setting_does_not_disable_plain_local_documents(work_mode, monkeypatch):
    values = {
        "knowledge_bases_enabled": "true",
        "knowledge_embedding_backend": "onnx",
        "knowledge_embedding_model": "local",
        "knowledge_ocr_enabled": "true",
        "knowledge_ocr_backend": "remote",
    }
    monkeypatch.setattr(gate, "embedding_prerequisites_ok_for_model", lambda _model: True)
    gate.assert_knowledge_usable(values.get)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["knowledge", "stt", "tts"])
async def test_ordinary_user_http_cannot_trigger_optional_models(work_mode, endpoint, monkeypatch):
    from octop.api.app import _install_exception_handlers
    from octop.api.deps import get_server, sign_token
    from octop.api.middleware.jwt_auth import install
    from octop.api.middleware.work_boundary import WorkBoundary
    from octop.api.routers import knowledge_bases, voice
    from octop.infra.users.identity import User

    user = User(41, "ordinary", "user", None, permissions=["knowledge_bases"])
    values = {"knowledge_bases_enabled": "true", "knowledge_embedding_backend": "remote"}
    services = SimpleNamespace(
        settings_repo=SimpleNamespace(get=values.get),
        secret_repo=SimpleNamespace(get=lambda _key: b"synthetic-secret-at-least-32-bytes"),
        provider_repo=SimpleNamespace(),
        voice_provider_repo=SimpleNamespace(),
        config=SimpleNamespace(access_token_ttl_seconds=86400),
    )
    server = SimpleNamespace(
        services=services,
        user_manager=SimpleNamespace(get_by_id=lambda _id: user),
        app_runtime=SimpleNamespace(work_entry_mode=True),
    )
    app = FastAPI()
    app.include_router(knowledge_bases.router, prefix="/api")
    app.include_router(voice.router, prefix="/api/voice")
    app.dependency_overrides[get_server] = lambda: server
    _install_exception_handlers(app)
    install(app, server)
    app.add_middleware(WorkBoundary, server=server)
    token = sign_token(services.secret_repo.get("jwt"), sub=41, uname="ordinary", role="user")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        headers = {"Authorization": "Bearer " + token}
        if endpoint == "knowledge":
            response = await client.post(
                "/api/knowledge-bases/k/documents/text",
                headers=headers,
                json={"name": "x", "format": "txt", "content": "synthetic"},
            )
        elif endpoint == "stt":
            response = await client.post(
                "/api/voice/stt",
                headers=headers,
                data={"provider": "cloud"},
                files={"audio": ("x.webm", b"synthetic", "audio/webm")},
            )
        else:
            response = await client.post(
                "/api/voice/tts", headers=headers, json={"text": "synthetic", "provider": "cloud"}
            )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"
