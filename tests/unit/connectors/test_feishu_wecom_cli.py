"""Retired Feishu CLI and supported WeCom CLI connector boundaries."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tests.support.fakes import fake_bin_path

from octop.infra.connectors.catalog import get_catalog_entry
from octop.infra.connectors.gateway.adapters import feishu_cli, wecom_cli
from octop.infra.connectors.gateway.registry import call_gateway_tool, mcp_tools_for_kind
from octop.infra.connectors.gateway.wecom_creds import materialize_wecom_bot_config
from octop.infra.errors import ErrorCode, OctopError


def test_feishu_is_not_registered_but_wecom_remains_available() -> None:
    assert get_catalog_entry("feishu-cli") is None
    assert get_catalog_entry("wecom-cli") is not None
    assert mcp_tools_for_kind("feishu-cli") == []
    assert mcp_tools_for_kind("wecom-cli")


def test_feishu_cli_paths_fail_before_resolving_or_running_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_cli(_name: str) -> str:
        raise AssertionError("retired Feishu path must not resolve or run lark-cli")

    monkeypatch.setattr(feishu_cli, "resolve_binary", unexpected_cli)
    monkeypatch.setattr(
        "octop.infra.connectors.gateway.feishu_creds.resolve_binary", unexpected_cli
    )
    operations = (
        lambda: call_gateway_tool("feishu-cli", {}, "doc", {"method": "+search"}),
        lambda: feishu_cli.call_tool({}, "doc", {"method": "+search"}),
        lambda: feishu_cli.probe_credentials({}),
        lambda: feishu_cli._prepare_env({}),  # noqa: SLF001
    )
    for operation in operations:
        with pytest.raises(OctopError) as exc:
            operation()
        assert exc.value.code is ErrorCode.FEATURE_DISABLED

    assert feishu_cli.list_tools() == []


def test_wecom_materialize_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        {
            "url": "https://example.com/mcp/doc",
            "type": "streamable-http",
            "is_authed": False,
            "biz_type": "doc",
        }
    ]

    def fake_fetch(*, bot_id: str, bot_secret: str) -> list[dict[str, Any]]:
        assert bot_id == "bid"
        assert bot_secret == "bsec"
        return items

    monkeypatch.setattr("octop.infra.connectors.gateway.wecom_creds._fetch_mcp_config", fake_fetch)
    materialize_wecom_bot_config(tmp_path, bot_id="bid", bot_secret="bsec")
    key = base64.b64decode((tmp_path / ".encryption_key").read_text(encoding="utf-8"))
    raw = (tmp_path / "bot.enc").read_bytes()
    bot = json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], None).decode("utf-8"))
    assert bot["id"] == "bid"
    assert bot["secret"] == "bsec"
    raw_mcp = (tmp_path / "mcp_config.enc").read_bytes()
    mcp = json.loads(AESGCM(key).decrypt(raw_mcp[:12], raw_mcp[12:], None).decode("utf-8"))
    assert mcp == items


def test_wecom_doc_invokes_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    monkeypatch.setattr(
        "octop.infra.connectors.gateway.adapters.wecom_cli.resolve_binary",
        lambda _name: fake_bin_path("wecom-cli"),
    )
    monkeypatch.setattr(
        "octop.infra.connectors.gateway.wecom_creds._fetch_mcp_config",
        lambda **_kwargs: [
            {
                "url": "https://example.com/mcp/doc",
                "type": "streamable-http",
                "biz_type": "doc",
            }
        ],
    )

    def fake_run(
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout_s: float = 30.0,
        cwd: str | None = None,
        stdin_text: str | None = None,
    ) -> str:
        del timeout_s, cwd, stdin_text
        captured["argv"] = argv
        captured["env"] = env
        return '{"ok":true}'

    monkeypatch.setattr("octop.infra.connectors.gateway.adapters.wecom_cli.run_cli", fake_run)
    result = wecom_cli.call_tool(
        {"bot_id": "b1", "bot_secret": "s1", "instance_id": "inst1"},
        "doc",
        {"method": "create_doc", "args": {"doc_type": 3}},
    )
    assert result == '{"ok":true}'
    assert captured["argv"][:3] == [fake_bin_path("wecom-cli"), "doc", "create_doc"]
    assert json.loads(captured["argv"][3]) == {"doc_type": 3}
    env = captured["env"] or {}
    assert "WECOM_CLI_CONFIG_DIR" in env
    config_dir = Path(str(env["WECOM_CLI_CONFIG_DIR"]))
    assert config_dir.is_relative_to(tmp_path)
    assert (config_dir / "bot.enc").is_file()
    assert (config_dir / "mcp_config.enc").is_file()
