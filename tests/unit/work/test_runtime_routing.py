from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from work_platform.authorization import ExecutionGrant
from work_platform.runtime_adapter import RuntimeBinding

from octop.infra.work.routing import (
    exchange_runtime_handoff,
    load_runtime_secret,
    resolve_entry_route,
    work_entry_mode_enabled,
)


def _binding() -> RuntimeBinding:
    return RuntimeBinding(
        "org-b",
        "runtime-b",
        "role-b",
        "volume-b",
        "database-b",
        "https://runtime-b.internal:8080",
        "handoff-b",
    )


def _grant() -> ExecutionGrant:
    return ExecutionGrant(
        octop_user_id=42,
        work_user_id="work-user-b",
        organization_id="org-b",
        agent_id="agent-b",
        member_status="active",
        membership_revision=3,
        policy_revision=2,
        runtime=_binding(),
    )


class Directory:
    def __init__(self) -> None:
        self.entry_grant = _grant()
        self.runtime_grant = _grant()
        self.consumed: set[str] = set()

    def resolve_entry_grant(self, octop_user_id: int, agent_id: str) -> ExecutionGrant | None:
        if (octop_user_id, agent_id) == (7, "agent-b"):
            return self.entry_grant
        return None

    def resolve_runtime_grant(self, work_user_id: str, agent_id: str) -> ExecutionGrant | None:
        if (work_user_id, agent_id) == ("work-user-b", "agent-b"):
            return self.runtime_grant
        return None

    def consume_runtime_handoff(self, handoff: object) -> ExecutionGrant | None:
        handoff_id = str(handoff.handoff_id)
        if handoff_id in self.consumed:
            return None
        self.consumed.add(handoff_id)
        return self.resolve_runtime_grant(str(handoff.work_user_id), str(handoff.agent_id))


def _secret_file(directory: Path) -> bytes:
    secret = b"runtime-b-secret-runtime-b-secret-00"
    (directory / "handoff-b").write_bytes(secret + b"\n")
    return secret


def test_entry_route_is_selected_from_the_trusted_directory(tmp_path: Path) -> None:
    secret = _secret_file(tmp_path)

    route = resolve_entry_route(Directory(), 7, "agent-b", tmp_path, connection_id="b" * 32)
    grant = exchange_runtime_handoff(
        Directory(),
        _binding(),
        secret,
        route.handoff_token,
        connection_id=route.connection_id,
    )

    assert route.endpoint == "https://runtime-b.internal:8080"
    assert grant.octop_user_id == 42
    assert grant.work_user_id == "work-user-b"


def test_runtime_rechecks_organization_after_handoff(tmp_path: Path) -> None:
    secret = _secret_file(tmp_path)
    directory = Directory()
    route = resolve_entry_route(directory, 7, "agent-b", tmp_path, connection_id="b" * 32)
    directory.runtime_grant = replace(directory.runtime_grant, organization_id="org-a")

    with pytest.raises(PermissionError):
        exchange_runtime_handoff(
            directory,
            _binding(),
            secret,
            route.handoff_token,
            connection_id=route.connection_id,
        )


def test_runtime_accepts_each_handoff_only_once(tmp_path: Path) -> None:
    secret = _secret_file(tmp_path)
    directory = Directory()
    route = resolve_entry_route(directory, 7, "agent-b", tmp_path, connection_id="b" * 32)

    assert exchange_runtime_handoff(
        directory,
        _binding(),
        secret,
        route.handoff_token,
        connection_id=route.connection_id,
    )
    with pytest.raises(PermissionError):
        exchange_runtime_handoff(
            directory,
            _binding(),
            secret,
            route.handoff_token,
            connection_id=route.connection_id,
        )


def test_connection_mismatch_is_rejected_without_consuming_handoff(tmp_path: Path) -> None:
    secret = _secret_file(tmp_path)
    directory = Directory()
    route = resolve_entry_route(directory, 7, "agent-b", tmp_path, connection_id="b" * 32)

    with pytest.raises(PermissionError):
        exchange_runtime_handoff(
            directory,
            _binding(),
            secret,
            route.handoff_token,
            connection_id="c" * 32,
        )
    assert exchange_runtime_handoff(
        directory,
        _binding(),
        secret,
        route.handoff_token,
        connection_id=route.connection_id,
    )


@pytest.mark.parametrize(
    "grant",
    [
        replace(_grant(), agent_id="agent-a"),
        replace(_grant(), organization_id="org-a"),
    ],
)
def test_entry_rejects_directory_grant_that_does_not_match_route(
    tmp_path: Path, grant: ExecutionGrant
) -> None:
    _secret_file(tmp_path)
    directory = Directory()
    directory.entry_grant = grant

    with pytest.raises(PermissionError):
        resolve_entry_route(directory, 7, "agent-b", tmp_path, connection_id="b" * 32)


def test_secret_reference_cannot_escape_its_directory(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        load_runtime_secret(tmp_path, "../handoff-b")


def test_entry_mode_requires_an_explicit_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORK_ENTRY_MODE", raising=False)
    assert work_entry_mode_enabled() is False
    monkeypatch.setenv("WORK_ENTRY_MODE", "1")
    assert work_entry_mode_enabled() is True
    monkeypatch.setenv("WORK_ENTRY_MODE", "maybe")
    with pytest.raises(ValueError):
        work_entry_mode_enabled()
