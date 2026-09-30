import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRITE_JOBS = {
    ".github/workflows/anti-spam-issues.yml": ["anti-spam"],
    ".github/workflows/auto-tag-on-release.yml": ["tag"],
    ".github/workflows/release.yml": ["publish", "github-release", "sync-develop", "trigger-fnos"],
    ".github/workflows/docker-publish.yml": ["docker"],
    ".github/workflows/fnos-build-fpk.yml": ["release"],
    ".github/workflows/octop-desktop.yml": ["release"],
    ".github/workflows/sync-main-to-develop.yml": ["sync"],
}


def job_block(text, name):
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line == f"  {name}:"), None)
    if start is None:
        return ""
    end = next(
        (i for i in range(start + 1, len(lines)) if re.fullmatch(r"  [A-Za-z0-9_-]+:", lines[i])),
        len(lines),
    )
    return "\n".join(lines[start:end])


class PublishWorkflowTests(unittest.TestCase):
    def test_write_jobs_are_restricted_to_the_original_upstream(self):
        for path, job_names in WRITE_JOBS.items():
            text = (ROOT / path).read_text(encoding="utf-8")
            for name in job_names:
                with self.subTest(workflow=path, job=name):
                    self.assertRegex(
                        job_block(text, name),
                        r"(?m)(?:^    if:.*github\.repository == 'TencentCloud/Octop'"
                        r"|^      github\.repository == 'TencentCloud/Octop')",
                    )

    def test_workflow_actions_use_immutable_commit_refs(self):
        for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            for action, ref in re.findall(r"(?m)^\s*uses:\s*([^@\s]+)@([^\s]+)", text):
                with self.subTest(workflow=path.name, action=action):
                    self.assertRegex(ref, r"\A[0-9a-f]{40}\Z")


if __name__ == "__main__":
    unittest.main()
