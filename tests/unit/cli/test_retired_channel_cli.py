from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from octop.cli.support import offline_ops
from octop.infra.errors import ErrorCode, OctopError


def test_offline_channel_create_rejects_feishu_before_opening_database(monkeypatch):
    def unexpected_open(_home):
        raise AssertionError("retired channel must be rejected before database access")

    monkeypatch.setattr(offline_ops, "open_cli_services", unexpected_open)

    with pytest.raises(OctopError) as exc:
        offline_ops.create_channel_offline(
            agent_id="agent",
            user_id=1,
            kind="feishu",
            name="legacy",
            config={"app_secret": "synthetic"},
        )

    assert exc.value.code == ErrorCode.FEATURE_DISABLED


def test_offline_channel_patch_allows_only_disabling_retired_channel(monkeypatch):
    row = SimpleNamespace(
        channel_id="channel",
        agent_id="agent",
        kind="lark",
        name="legacy",
        enabled=1,
        config_json="{}",
    )

    class ChannelRepo:
        updated = False

        def get(self, _channel_id):
            return row

        def update(self, _channel_id, **kwargs):
            self.updated = True
            assert kwargs == {"name": None, "config_json": None, "enabled": False}
            row.enabled = 0

    repo = ChannelRepo()
    services = SimpleNamespace(channel_repo=repo)

    @contextmanager
    def open_services(_home):
        yield services

    monkeypatch.setattr(offline_ops, "open_cli_services", open_services)

    result = offline_ops.patch_channel_offline("agent", "channel", enabled=False)
    assert result["enabled"] is False
    assert repo.updated is True

    repo.updated = False
    with pytest.raises(OctopError) as exc:
        offline_ops.patch_channel_offline("agent", "channel", name="re-enable")

    assert exc.value.code == ErrorCode.FEATURE_DISABLED
    assert repo.updated is False
