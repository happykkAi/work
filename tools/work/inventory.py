"""Render only approved, non-secret Work baseline evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

UNKNOWN = "UNKNOWN"

_TEXT_PATTERNS = {
    "application_sha": re.compile(r"[0-9a-fA-F]{7,40}\Z"),
    "api_sha": re.compile(r"[0-9a-fA-F]{7,40}\Z"),
    "worker_sha": re.compile(r"[0-9a-fA-F]{7,40}\Z"),
    "migration_ledger": re.compile(r"[0-9]{4}(?:,[0-9]{4}){0,15}\Z"),
}
_RECOVERY_STATES = {"VERIFIED", "NOT_VERIFIED"}
_NUMBER_FIELDS = (
    "organization_count",
    "active_concurrency",
    "data_bytes",
    "largest_object_bytes",
    "recent_growth_bytes",
    "cpu_count",
    "memory_bytes",
    "storage_bytes",
)


def normalize_inventory(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Keep a fixed safe field set and distinguish missing data from zero."""
    raw = evidence.get("production")
    production = raw if isinstance(raw, dict) else {}
    result: dict[str, Any] = {}

    for name, pattern in _TEXT_PATTERNS.items():
        value = production.get(name)
        result[name] = value if isinstance(value, str) and pattern.fullmatch(value) else UNKNOWN

    recovery = production.get("admin_recovery_path")
    result["admin_recovery_path"] = (
        recovery.upper()
        if isinstance(recovery, str) and recovery.upper() in _RECOVERY_STATES
        else UNKNOWN
    )

    for name in _NUMBER_FIELDS:
        value = production.get(name)
        result[name] = value if type(value) is int and value >= 0 else UNKNOWN

    return {"production": result}


def render_markdown(report: dict[str, dict[str, Any]]) -> str:
    rows = ["# Work production baseline", "", "| Evidence | Value |", "|---|---|"]
    for name, value in report["production"].items():
        rows.append(f"| `{name}` | `{value}` |")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="JSON containing non-secret observed evidence")
    parser.add_argument("output", type=Path, help="Markdown report path")
    args = parser.parse_args()

    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    args.output.write_text(render_markdown(normalize_inventory(evidence)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
