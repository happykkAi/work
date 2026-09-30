"""Check a Work platform wheel and create a source-version report."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any

_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")


def verify_distribution(wheel: Path) -> bool:
    """Return true only when the built wheel contains the Work package."""
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    return "work_platform/__init__.py" in names and any(
        name.startswith("work_platform/") and name.endswith(".py") for name in names
    )


def build_version_report(work_sha: str, octop_sha: str) -> dict[str, Any]:
    """Keep both source identities explicit in every Work build manifest."""
    if not _SHA.fullmatch(work_sha) or not _SHA.fullmatch(octop_sha):
        raise ValueError("source SHAs must be full 40-character Git commit IDs")
    return {
        "manifest_version": 1,
        "source": {"work_sha": work_sha.lower(), "octop_sha": octop_sha.lower()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--work-sha", required=True)
    parser.add_argument("--octop-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not verify_distribution(args.wheel):
        parser.error(f"Work platform package missing from {args.wheel}")
    args.output.write_text(
        json.dumps(build_version_report(args.work_sha, args.octop_sha), indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
