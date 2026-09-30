from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from work_platform.runtime_adapter import RuntimeBinding
from work_platform.runtime_context import ExecutionContext
from work_platform.runtime_handoff import RuntimeHandoff

from octop.infra.work.control_plane import WorkControlPlane


class _Rows:
    def fetchall(self) -> list[dict[str, Any]]:
        return [
            {
                "octop_user_id": 41,
                "work_user_id": "work-user-a",
                "organization_id": "org-a",
                "member_status": "active",
                "membership_revision": 3,
                "policy_revision": 2,
                "agent_id": "agent-a",
                "runtime_id": "runtime-a",
                "database_role": "role-a",
                "volume_id": "volume-a",
                "secret_ref": "secret-a",
            }
        ]

    def fetchone(self) -> dict[str, Any]:
        return self.fetchall()[0]


class _Connection:
    def execute(self, _query: str, _params: tuple[Any, ...]) -> _Rows:
        return _Rows()


class _Database:
    @contextmanager
    def connect(self) -> Any:
        yield _Connection()


class _ContextConnection:
    closed = False

    def __init__(self) -> None:
        self.params: tuple[Any, ...] | None = None
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> _Rows:
        self.params = params
        self.calls.append((query, params))
        return _Rows()


class _ContextDatabase:
    def __init__(self) -> None:
        self.connection = _ContextConnection()

    @contextmanager
    def connect(self) -> Any:
        yield self.connection

    @contextmanager
    def transaction(self) -> Any:
        yield self.connection


class _EntryRows:
    def fetchall(self) -> list[dict[str, Any]]:
        return [
            {
                "octop_user_id": 7,
                "work_user_id": "work-user-b",
                "organization_id": "org-b",
                "member_status": "active",
                "membership_revision": 5,
                "policy_revision": 3,
                "agent_id": "agent-b",
                "runtime_id": "runtime-b",
                "database_role": "role-b",
                "volume_id": "volume-b",
                "secret_ref": "database-b",
                "endpoint": "https://runtime-b.internal:8080",
                "handoff_secret_ref": "handoff-b",
            }
        ]


class _EntryConnection:
    def execute(self, _query: str, _params: tuple[Any, ...]) -> _EntryRows:
        return _EntryRows()


class _EntryDatabase:
    @contextmanager
    def connect(self) -> Any:
        yield _EntryConnection()


class _HandoffConnection:
    def __init__(self) -> None:
        self.consumed: set[str] = set()
        self.insert_query = ""

    def execute(self, query: str, params: tuple[Any, ...]) -> _Rows | None:
        if query.startswith("SELECT i.octop_user_id"):
            return _Rows()
        if query.startswith("INSERT INTO work_runtime_handoffs"):
            self.insert_query = query
            handoff_id = str(params[0])
            if handoff_id in self.consumed:
                return _NoRow()
            self.consumed.add(handoff_id)
            return _Rows()
        raise AssertionError(query)


class _NoRow:
    def fetchone(self) -> None:
        return None


class _HandoffDatabase:
    def __init__(self) -> None:
        self.connection = _HandoffConnection()

    @contextmanager
    def transaction(self) -> Any:
        yield self.connection


def test_grant_is_denied_when_database_mapping_targets_another_local_runtime_resource() -> None:
    control = object.__new__(WorkControlPlane)
    control.runtime_id = "runtime-a"
    control._db = _Database()
    control.expected_runtime_binding = RuntimeBinding(
        "org-a", "runtime-a", "role-a", "volume-a", "secret-a"
    )

    mismatches = (
        RuntimeBinding("org-a", "runtime-a", "role-b", "volume-a", "secret-a"),
        RuntimeBinding("org-a", "runtime-a", "role-a", "volume-b", "secret-a"),
        RuntimeBinding("org-a", "runtime-a", "role-a", "volume-a", "secret-b"),
    )
    assert control.resolve_grant(41, "agent-a") is not None
    control.expected_runtime_binding = None
    assert control.resolve_grant(41, "agent-a") is None

    for expected in mismatches:
        control.expected_runtime_binding = expected
        assert control.resolve_grant(41, "agent-a") is None


def test_runtime_handoff_resolves_global_identity_to_local_runtime_user() -> None:
    control = object.__new__(WorkControlPlane)
    control.runtime_id = "runtime-a"
    control._db = _Database()
    control.expected_runtime_binding = RuntimeBinding(
        "org-a", "runtime-a", "role-a", "volume-a", "secret-a"
    )

    grant = control.resolve_runtime_grant("work-user-a", "agent-a")

    assert grant is not None
    assert grant.work_user_id == "work-user-a"
    assert grant.octop_user_id == 41
    assert grant.runtime.runtime_id == "runtime-a"


def test_runtime_handoff_consumption_is_atomic_and_one_time() -> None:
    control = object.__new__(WorkControlPlane)
    control.runtime_id = "runtime-a"
    control._db = _HandoffDatabase()
    control._secured = False
    control.expected_runtime_binding = RuntimeBinding(
        "org-a", "runtime-a", "role-a", "volume-a", "secret-a"
    )
    now = datetime.now(UTC)
    handoff = RuntimeHandoff(
        connection_id="b" * 32,
        work_user_id="work-user-a",
        organization_id="org-a",
        agent_id="agent-a",
        runtime_id="runtime-a",
        purpose="runtime-handoff",
        handoff_id="handoff-a",
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
    )

    assert control.consume_runtime_handoff(handoff) is not None
    assert "WHERE ? > now()" in control._db.connection.insert_query
    assert control.consume_runtime_handoff(handoff) is None


def test_context_query_binds_runtime_resources_before_run_fields() -> None:
    database = _ContextDatabase()
    control = object.__new__(WorkControlPlane)
    control.runtime_id = "runtime-a"
    control._db = database
    control._executor_id = "executor-a"
    control._executor = _ContextConnection()
    control._secured = False
    control.expected_runtime_binding = RuntimeBinding(
        "org-a", "runtime-a", "role-a", "volume-a", "secret-a"
    )
    now = datetime.now(UTC)
    context = ExecutionContext(
        work_user_id="work-user-a",
        organization_id="org-a",
        project_id=None,
        workspace_scope="organization",
        run_id="run-a",
        budget_scope_id="thread-a",
        policy_revision=2,
        membership_revision=3,
        allowed_asset_versions=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        connection_id="c" * 32,
        agent_id="agent-a",
        runtime_id="runtime-a",
        octop_user_id=41,
    )

    assert control.context_is_current(context) is True
    assert database.connection.params == (
        "role-a",
        "volume-a",
        "secret-a",
        "run-a",
        41,
        "work-user-a",
        "org-a",
        "agent-a",
        "runtime-a",
        "thread-a",
        3,
        2,
        "executor-a",
        "running",
        "running",
        "running",
    )


def test_create_run_persists_and_logs_the_forwarded_connection_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = _ContextDatabase()
    control = object.__new__(WorkControlPlane)
    control.runtime_id = "runtime-a"
    control._db = database
    control._executor_id = "executor-a"
    control._executor = _ContextConnection()
    control._secured = False
    now = datetime.now(UTC)
    context = ExecutionContext(
        work_user_id="work-user-a",
        organization_id="org-a",
        project_id=None,
        workspace_scope="organization",
        run_id="run-a",
        budget_scope_id="thread-a",
        policy_revision=2,
        membership_revision=3,
        allowed_asset_versions=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        connection_id="c" * 32,
        agent_id="agent-a",
        runtime_id="runtime-a",
        octop_user_id=41,
    )

    with caplog.at_level("INFO"):
        control.create_run(context)

    query, params = database.connection.calls[-1]
    assert "connection_id" in query
    assert params[7] == "c" * 32
    record = caplog.records[-1]
    assert record.message == "work_run_created"
    assert record.work_connection_id == "c" * 32
    assert record.work_run_id == "run-a"


def test_entry_identity_selects_the_bound_remote_runtime() -> None:
    control = object.__new__(WorkControlPlane)
    control.runtime_id = "work-entry"
    control._db = _EntryDatabase()
    control.expected_runtime_binding = None

    grant = control.resolve_entry_grant(7, "agent-b")

    assert grant is not None
    assert grant.work_user_id == "work-user-b"
    assert grant.organization_id == "org-b"
    assert grant.runtime.runtime_id == "runtime-b"
    assert grant.runtime.require_handoff() == (
        "https://runtime-b.internal:8080",
        "handoff-b",
    )
