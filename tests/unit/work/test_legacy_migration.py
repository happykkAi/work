from __future__ import annotations

import copy
import hashlib

import pytest
from work_platform.migration import MigrationError, prepare_snapshot


def snapshot():
    return {
        "users": [{"id": 1, "openId": "old-a", "role": "admin"}, {"id": 2, "openId": "old-b"}],
        "organizations": [{"id": "a", "name": "甲"}, {"id": "b", "name": "乙"}],
        "organizationMembers": [
            {
                "id": "m1",
                "organizationId": "a",
                "userId": 1,
                "memberRole": "member",
                "memberStatus": "suspended",
            },
            {
                "id": "m2",
                "organizationId": "b",
                "userId": 2,
                "memberRole": "owner",
                "memberStatus": "active",
            },
        ],
        "organizationProjects": [
            {
                "id": "p",
                "organizationId": "a",
                "name": "历史项目",
                "ownerUserId": 1,
                "lifecycle": "closed",
                "budgetPlannedCents": 123,
                "budgetActualCents": 0,
            }
        ],
        "workThreads": [
            {
                "id": "t",
                "organizationId": "a",
                "projectId": "p",
                "createdByUserId": 1,
                "status": "archived",
            }
        ],
        "workMessages": [
            {"id": "msg", "threadId": "t", "sender": "yayye", "content": "合成历史正文\n完整保留"}
        ],
        "personalFiles": [
            {
                "id": "f",
                "organizationId": "a",
                "ownerUserId": 1,
                "objectKey": "private/f",
                "sizeBytes": 4,
                "status": "ready",
                "normalizedText": "合成解析正文",
                "contentHash": hashlib.sha256("合成解析正文".encode()).hexdigest(),
            }
        ],
        "taskRuns": [
            {
                "id": "r",
                "threadId": "t",
                "status": "awaiting_confirmation",
                "collaborationState": "executing_confirmed",
            }
        ],
        "taskSteps": [{"id": "s", "taskRunId": "r", "state": "needs_confirmation"}],
        "pendingActions": [
            {
                "id": "action",
                "taskRunId": "r",
                "status": "pending",
                "actionType": "send_message",
                "payload": {"target": "synthetic"},
            }
        ],
        "workOutbox": [],
        "projectReviews": [],
        "organizationResources": [],
        "workAiCallBudgets": [
            {
                "scopeId": "task:t",
                "usageDate": "2026-09-29",
                "callCount": 20,
                "attemptIds": '["' + "a" * 64 + '"]',
            },
            {"scopeId": "user:1", "usageDate": "2026-09-30", "callCount": 99, "attemptIds": "[]"},
            {"scopeId": "org:a", "usageDate": "2026-09-30", "callCount": 499, "attemptIds": "[]"},
        ],
    }


def test_preserves_business_relationships_states_and_lifetime_quota(tmp_path):
    (tmp_path / "private").mkdir()
    (tmp_path / "private/f").write_bytes(b"data")
    source = snapshot()
    before = copy.deepcopy(source)
    result = prepare_snapshot(source, tmp_path, {"private/f": hashlib.sha256(b"data").hexdigest()})
    assert source == before
    assert result["memberships"][0] == ("a", "legacy:1", "member", "suspended", 1)
    assert result["budgets"] == [
        ("task", "t", "2026-09-29", 20),
        ("user", "legacy:1", "2026-09-30", 99),
        ("organization", "a", "2026-09-30", 499),
    ]
    assert result["records"]["organizationProjects"][0]["budgetPlannedCents"] == 123
    assert result["records"]["organizationProjects"][0]["budgetActualCents"] == 0
    assert result["records"]["workMessages"][0]["content"] == before["workMessages"][0]["content"]
    assert result["dispositions"]["taskRuns"] == "read_only_history_no_execution"
    assert result["dispositions"]["pendingActions"] == "read_only_history_no_execution"
    assert result["files"][0]["sha256"] == hashlib.sha256(b"data").hexdigest()


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "orphan",
        "cross_org",
        "duplicate",
        "bad_status",
        "bad_quota",
        "path",
        "changed_file",
        "missing_file",
    ],
)
def test_invalid_source_is_explicitly_rejected_without_partial_acceptance(tmp_path, case):
    source = snapshot()
    (tmp_path / "private").mkdir()
    (tmp_path / "private/f").write_bytes(b"data")
    if case == "unknown":
        source["unknownTable"] = []
    if case == "orphan":
        source["workMessages"][0]["threadId"] = "absent"
    if case == "cross_org":
        source["workThreads"][0]["organizationId"] = "b"
    if case == "duplicate":
        source["users"].append(dict(source["users"][0]))
    if case == "bad_status":
        source["organizationMembers"][0]["memberStatus"] = "invented"
    if case == "bad_quota":
        source["workAiCallBudgets"][0]["callCount"] = -1
    if case == "path":
        source["personalFiles"][0]["objectKey"] = "../outside"
    if case == "changed_file":
        (tmp_path / "private/f").write_bytes(b"evil")
    if case == "missing_file":
        (tmp_path / "private/f").unlink()
    with pytest.raises(MigrationError):
        prepare_snapshot(source, tmp_path, {"private/f": hashlib.sha256(b"data").hexdigest()})
