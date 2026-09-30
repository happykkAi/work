"""Retired Feishu user-auth boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.connectors.gateway import feishu_creds, feishu_user_auth
from octop.infra.errors import ErrorCode, OctopError


def test_user_auth_and_cli_config_are_disabled_before_cli_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unexpected_cli(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("retired Feishu auth must not resolve credentials or invoke lark-cli")

    monkeypatch.setattr(feishu_user_auth, "run_cli", unexpected_cli)
    monkeypatch.setattr(feishu_creds, "run_cli", unexpected_cli)
    monkeypatch.setattr(feishu_creds, "resolve_binary", unexpected_cli)

    operations = (
        lambda: feishu_user_auth.start_user_device_login(
            config_dir=tmp_path, app_id="synthetic", app_secret="synthetic"
        ),
        lambda: feishu_user_auth.complete_user_device_login(
            config_dir=tmp_path,
            app_id="synthetic",
            app_secret="synthetic",
            device_code="synthetic",
        ),
        lambda: feishu_creds.prepare_feishu_cli_env(
            tmp_path, app_id="synthetic", app_secret="synthetic"
        ),
        lambda: feishu_creds.ensure_feishu_cli_config(
            tmp_path,
            binary="lark-cli",
            app_id="synthetic",
            app_secret="synthetic",
            env={},
        ),
    )
    for operation in operations:
        with pytest.raises(OctopError) as exc:
            operation()
        assert exc.value.code is ErrorCode.FEATURE_DISABLED
