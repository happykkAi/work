"""Disabled Feishu auth preview must not inspect or refresh tokens."""

from __future__ import annotations

import pytest

from octop.infra.connectors.gateway import feishu_user_auth


def test_preview_reports_disabled_without_reading_saved_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("retired Feishu preview must not inspect or refresh auth")

    monkeypatch.setattr(feishu_user_auth, "prepare_feishu_cli_env", unexpected_call)
    monkeypatch.setattr(feishu_user_auth, "read_auth_status", unexpected_call)

    result = feishu_user_auth.live_user_auth_preview(
        {"app_id": "synthetic", "app_secret": "synthetic"}
    )

    assert result == {
        "disabled": True,
        "status_message": "飞书相关功能已停用，历史记录保留",
    }
