"""Retired Feishu bot-creator boundaries."""

from __future__ import annotations

import json
import sys

import pytest

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.bot_creators import feishu_bot_creator as creator
from octop.infra.gateway.bot_creators import feishu_runner


def test_register_feishu_app_is_disabled_before_sdk_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "synthetic-app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "synthetic-secret")
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "synthetic-verification")

    def unexpected_call(**_kwargs: object) -> None:
        raise AssertionError("retired Feishu app creation must not call the SDK")

    monkeypatch.setattr(creator.lark, "register_app", unexpected_call)

    with pytest.raises(OctopError) as exc:
        creator.register_feishu_app()

    assert exc.value.code is ErrorCode.FEATURE_DISABLED
    assert exc.value.message == "飞书相关功能已停用，历史记录保留"


def test_direct_greeting_is_disabled_before_token_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        creator.urllib.request,
        "urlopen",
        lambda *args, **kwargs: calls.append(args[0]),
    )

    with pytest.raises(OctopError) as exc:
        creator._send_greeting(
            "app-id",
            "app-secret",
            "open-id",
            open_base="https://example.invalid",
            greeting="hello",
        )

    assert exc.value.code is ErrorCode.FEATURE_DISABLED
    assert exc.value.message == "飞书相关功能已停用，历史记录保留"
    assert calls == []


def test_feishu_creator_cli_reports_disabled(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def unexpected_call(**_kwargs: object) -> None:
        raise AssertionError("retired Feishu CLI must not call the SDK")

    monkeypatch.setattr(creator.lark, "register_app", unexpected_call)
    monkeypatch.setattr(sys, "argv", ["feishu_bot_creator.py", "create"])
    with pytest.raises(SystemExit) as exc:
        creator.main()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["level"] == "error"
    assert payload["message"] == "飞书相关功能已停用，历史记录保留"


def test_feishu_runner_is_disabled_before_spawning(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_spawn(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("retired Feishu creator must not spawn")

    monkeypatch.setattr(feishu_runner.subprocess, "Popen", unexpected_spawn)

    with pytest.raises(OctopError) as exc:
        feishu_runner.start_feishu_creator(platform="feishu")

    assert exc.value.code is ErrorCode.FEATURE_DISABLED
