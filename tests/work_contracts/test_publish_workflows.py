import re
import unittest
from pathlib import Path

import yaml

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
    def test_work_pipeline_installs_locked_frontend_before_gates(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/work-ci.yml").read_text(encoding="utf-8")
        )
        commands = [step.get("run", "") for step in workflow["jobs"]["checks"]["steps"]]
        install = next(i for i, command in enumerate(commands) if "npm ci --prefix" in command)
        check = next(i for i, command in enumerate(commands) if "make check-all" in command)
        self.assertLess(install, check)

    def test_portable_python_release_and_asset_tag_match(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/octop-desktop.yml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            workflow["env"]["PBS_BASE_URL"].rsplit("/", 1)[1], workflow["env"]["PBS_TAG"]
        )

    def test_work_build_binds_target_image_to_checked_source(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/work-ci.yml").read_text(encoding="utf-8")
        )
        commands = "\n".join(step.get("run", "") for step in workflow["jobs"]["checks"]["steps"])
        self.assertIn("--platform linux/amd64", commands)
        self.assertIn('org.opencontainers.image.revision="$GITHUB_SHA"', commands)
        self.assertIn("docker save", commands)

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
