"""Retired Feishu SSO paths stay closed while legacy config remains queryable."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from octop.config import OctopConfig
from octop.infra.auth.sso.crypto import encrypt_secret
from octop.infra.auth.sso.providers.feishu import FeishuAdapter
from octop.infra.auth.sso.service import SsoService
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.manager import UserManager
from octop.infra.utils.paths import PathLayout


@pytest.fixture
def service(tmp_path):
    paths = PathLayout(tmp_path / ".octop")
    paths.ensure_root()
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=OctopConfig())
    return SsoService(services, UserManager(services))


def _feishu_row(service: SsoService):
    secret = encrypt_secret(service._services.secret_repo, "synthetic-secret")
    return service._services.sso_repo.upsert_by_kind(
        "feishu",
        enabled=True,
        display_name="Feishu",
        issuer="",
        client_id="synthetic-app",
        client_secret_enc=secret,
        scopes="",
        dashboard_origin=None,
        extra={"region": "feishu"},
    )


def test_legacy_feishu_sso_is_reported_retired_without_exposing_credentials(
    service: SsoService,
) -> None:
    _feishu_row(service)
    with patch.object(service._user_manager, "count", return_value=1):
        status = service.providers_status()

    feishu = next(item for item in status["providers"] if item["kind"] == "feishu")
    assert feishu["enabled"] is False
    assert feishu["retired"] is True
    assert feishu["status_message"] == "飞书相关功能已停用，历史记录保留"

    config = service.get_config_for_kind("feishu", public_base="https://work.example")
    assert config["enabled"] is False
    assert config["retired"] is True
    assert config["status_message"] == "飞书相关功能已停用，历史记录保留"
    assert config["client_id"] == ""
    assert config["has_client_secret"] is False


def test_feishu_sso_cannot_be_reconfigured_or_started(service: SsoService) -> None:
    with pytest.raises(OctopError) as save_error:
        service.put_config_for_kind("feishu", {"enabled": True, "client_id": "new"})
    with pytest.raises(OctopError) as login_error:
        service.start_login_for_kind(
            "feishu", redirect_after=None, public_base="https://work.example"
        )

    assert save_error.value.code is ErrorCode.FEATURE_DISABLED
    assert login_error.value.code is ErrorCode.FEATURE_DISABLED


@pytest.mark.parametrize("operation", ["authorize", "complete", "test_connection"])
def test_adapter_methods_block_before_token_or_business_request(
    service: SsoService,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    row = _feishu_row(service)
    adapter = FeishuAdapter(service)
    requests: list[str] = []
    monkeypatch.setattr(
        service,
        "_http_client",
        lambda: requests.append("http") or pytest.fail("retired Feishu path opened HTTP"),
    )
    monkeypatch.setattr(
        "octop.infra.auth.sso.providers.feishu.decrypt_secret",
        lambda *_args: requests.append("secret") or pytest.fail("retired Feishu path read secret"),
    )

    with pytest.raises(OctopError) as exc:
        if operation == "authorize":
            adapter.authorize_url(
                row=row,
                state="synthetic-state",
                nonce="synthetic-nonce",
                code_challenge="synthetic-challenge",
                redirect_uri="https://work.example/callback",
            )
        elif operation == "complete":
            adapter.complete_login(
                "synthetic-code",
                row=row,
                login_state=None,  # type: ignore[arg-type]
                redirect_uri="https://work.example/callback",
            )
        else:
            adapter.test_connection(row)

    assert exc.value.code is ErrorCode.FEATURE_DISABLED
    assert requests == []
