"""Validate an explicit legacy source snapshot before any destination write.

Historical operations remain records, never runnable queue/checkpoint state.
Source credentials and live verification/invitation tokens are not public history.
This projection is not by itself a completed business-data migration.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

TABLES = frozenset(
    {
        "users",
        "phoneVerificationChallenges",
        "organizations",
        "aiToolPreferences",
        "workAiCallBudgets",
        "organizationResources",
        "personalFiles",
        "knowledgeCitations",
        "knowledgeDeleteRequests",
        "knowledgeSettings",
        "organizationRegistrationPolicies",
        "organizationMembers",
        "userIdentities",
        "accountSecurityEvents",
        "accountSecurityRateLimits",
        "identityReceiptConsumptions",
        "organizationInvitations",
        "workspaces",
        "organizationProjects",
        "projectReviews",
        "workThreads",
        "workMessages",
        "taskRuns",
        "taskSteps",
        "pendingActions",
        "workOutbox",
        "auditLogs",
        "organizationSkills",
        "organizationApplicationProfiles",
        "opportunityApplications",
        "opportunityReminderEvents",
        "feishuConnections",
        "__drizzle_migrations",
    }
)
REQUIRED = frozenset(
    {
        "users",
        "organizations",
        "organizationMembers",
        "organizationProjects",
        "workThreads",
        "workMessages",
        "personalFiles",
        "taskRuns",
        "taskSteps",
        "pendingActions",
        "workOutbox",
        "projectReviews",
        "organizationResources",
        "workAiCallBudgets",
    }
)
_TRANSIENT = {
    "phoneVerificationChallenges",
    "identityReceiptConsumptions",
    "accountSecurityRateLimits",
    "organizationInvitations",
}
_HISTORY = {
    "taskRuns",
    "taskSteps",
    "pendingActions",
    "workOutbox",
    "opportunityReminderEvents",
    "feishuConnections",
}
_SECRET_FIELDS = {
    "passwordHash",
    "codeHash",
    "token",
    "accessToken",
    "refreshToken",
    "appSecret",
    "appToken",
    "inviteToken",
    "tokenHash",
    "jti",
    "verificationId",
}


class MigrationError(ValueError):
    """A source item cannot safely be mapped; no implicit drop or coercion."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _public_history(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _public_history(item) for key, item in value.items() if key not in _SECRET_FIELDS
        }
    if isinstance(value, list):
        return [_public_history(item) for item in value]
    return value


def prepare_snapshot(
    tables: dict[str, list[dict[str, Any]]], objects: Path, object_hashes: dict[str, str]
) -> dict[str, Any]:
    unknown, missing = tables.keys() - TABLES, REQUIRED - tables.keys()
    if unknown or missing:
        raise MigrationError(f"unmapped tables={sorted(unknown)} missing tables={sorted(missing)}")
    source = copy.deepcopy(tables)
    by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for table, rows in source.items():
        if not isinstance(rows, list):
            raise MigrationError(f"invalid rows: {table}")
        mapping = {}
        for row in rows:
            if not isinstance(row, dict):
                raise MigrationError(f"invalid row: {table}")
            field = {
                "workAiCallBudgets": "scopeId",
                "accountSecurityRateLimits": "subjectHash",
            }.get(table, "id")
            key = str(row.get(field, ""))
            if not key or key == "None" or key in mapping:
                raise MigrationError(f"missing or duplicate source id: {table}")
            mapping[key] = row
        by_id[table] = mapping

    def reference(table: str, identifier: Any) -> dict[str, Any]:
        row = by_id.get(table, {}).get(str(identifier))
        if row is None:
            raise MigrationError(f"orphan reference to {table}")
        return row

    memberships = []
    member_keys = set()
    for row in source["organizationMembers"]:
        org, uid = row["organizationId"], str(row["userId"])
        reference("organizations", org)
        reference("users", uid)
        if row["memberRole"] not in {"owner", "manager", "member"} or row["memberStatus"] not in {
            "active",
            "suspended",
            "removed",
        }:
            raise MigrationError("unsupported membership role/state")
        if (org, uid) in member_keys:
            raise MigrationError("duplicate institution membership")
        member_keys.add((org, uid))
        memberships.append((org, "legacy:" + uid, row["memberRole"], row["memberStatus"], 1))

    links = {
        "projectId": "organizationProjects",
        "threadId": "workThreads",
        "taskRunId": "taskRuns",
        "sourceFileId": "personalFiles",
        "publishedResourceId": "organizationResources",
        "personalFileId": "personalFiles",
    }
    for table, rows in source.items():
        for row in rows:
            org = row.get("organizationId")
            if org is not None:
                reference("organizations", org)
            for field, value in row.items():
                if value is None:
                    continue
                if field.endswith("UserId") or field == "userId":
                    if value == 0 and table == "aiToolPreferences" and field == "userId":
                        continue
                    reference("users", value)
                if field in links:
                    linked = reference(links[field], value)
                    if org is not None and linked.get("organizationId", org) != org:
                        raise MigrationError("cross-institution source relationship")
            if table == "knowledgeCitations":
                target = {"personal": "personalFiles", "organization": "organizationResources"}.get(
                    row["resourceKind"]
                )
                if (
                    target is None
                    or reference(target, row["resourceId"]).get("organizationId") != org
                ):
                    raise MigrationError("invalid citation scope")
            actor = row.get("createdByUserId", row.get("ownerUserId"))
            if org is not None and actor is not None and (org, str(actor)) not in member_keys:
                raise MigrationError("business owner has no institution membership")

    for row in source["organizationProjects"]:
        if row["lifecycle"] not in {"planning", "active", "closing", "closed"}:
            raise MigrationError("unsupported project lifecycle")
        for field in ("budgetPlannedCents", "budgetActualCents"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise MigrationError("invalid project amount in cents")
    for row in source["workThreads"]:
        if row["status"] not in {"active", "archived"}:
            raise MigrationError("unsupported thread state")
    for row in source["workMessages"]:
        if row["sender"] not in {"social_worker", "yayye"} or not isinstance(row["content"], str):
            raise MigrationError("unsupported historical message")

    files = []
    root = objects.resolve()
    for row in source["personalFiles"]:
        if row["status"] not in {
            "awaiting_upload",
            "uploaded",
            "processing",
            "ready",
            "failed",
            "submitted",
            "rejected",
            "published",
            "archived",
        }:
            raise MigrationError("unsupported file state")
        if row["status"] == "awaiting_upload":
            continue
        key = row["objectKey"]
        path = (root / key).resolve()
        if not path.is_relative_to(root) or path == root or not path.is_file():
            raise MigrationError("source file missing or outside private object root")
        expected = object_hashes.get(key, "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise MigrationError("source file has no verified object hash")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected or path.stat().st_size != row["sizeBytes"]:
            raise MigrationError("source file integrity mismatch")
        text = row.get("normalizedText")
        if (
            text is not None
            and row.get("contentHash") is not None
            and hashlib.sha256(text.encode()).hexdigest() != row["contentHash"]
        ):
            raise MigrationError("parsed text integrity mismatch")
        files.append(
            {
                "file_id": row["id"],
                "object_key": key,
                "sha256": actual,
                "size_bytes": path.stat().st_size,
            }
        )

    budgets: list[tuple[str, str, str, int]] = []
    attempts: list[tuple[str, str, str, str]] = []
    for row in source["workAiCallBudgets"]:
        prefix, sep, identifier = row["scopeId"].partition(":")
        scope_table = {"task": "workThreads", "user": "users", "org": "organizations"}.get(prefix)
        if not sep or not identifier or scope_table is None:
            raise MigrationError("unsupported quota scope")
        reference(scope_table, identifier)
        count = row["callCount"]
        if type(count) is not int or count < 0:
            raise MigrationError("invalid consumed quota")
        try:
            day = date.fromisoformat(row["usageDate"]).isoformat()
            keys = json.loads(row["attemptIds"])
        except (ValueError, TypeError) as exc:
            raise MigrationError("invalid quota date/attempt ledger") from exc
        if (
            not isinstance(keys, list)
            or any(
                not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) for key in keys
            )
            or len(set(keys)) != len(keys)
            or len(keys) > count
        ):
            raise MigrationError("invalid quota attempt identifiers")
        kind = "organization" if prefix == "org" else prefix
        target = "legacy:" + identifier if prefix == "user" else identifier
        budgets.append((kind, target, day, count))
        attempts.extend((kind, target, day, key) for key in keys)

    dispositions = {
        table: (
            "invalidate_live_state"
            if table in _TRANSIENT
            else "read_only_history_no_execution"
            if table in _HISTORY
            else "validated_business_projection"
        )
        for table in source
    }
    records = {
        table: [_public_history(row) for row in rows]
        for table, rows in source.items()
        if table not in _TRANSIENT
    }
    return {
        "source_digest": digest(source),
        "records": records,
        "dispositions": dispositions,
        "source_counts": {table: len(rows) for table, rows in source.items()},
        "memberships": memberships,
        "budgets": budgets,
        "budget_attempts": attempts,
        "files": files,
    }
