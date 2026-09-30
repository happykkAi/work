import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from tools.work.verify_distribution import build_version_report, verify_distribution
except ImportError as exc:
    build_version_report = None
    verify_distribution = None
    _import_error = exc
else:
    _import_error = None


class DistributionTests(unittest.TestCase):
    def test_work_platform_wheel_is_importable(self):
        wheel_path = os.environ.get("WORK_PLATFORM_WHEEL")
        if not wheel_path:
            self.skipTest("WORK_PLATFORM_WHEEL is set by the distribution build gate")
        wheel_path = str(Path(wheel_path).resolve())

        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from work_platform.authorization import issue_execution_context; "
                    "print(issue_execution_context.__name__)",
                ],
                cwd=directory,
                env={**os.environ, "PYTHONPATH": wheel_path},
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "issue_execution_context")

    def test_distribution_contains_work_platform(self):
        self.assertIsNotNone(verify_distribution, f"distribution verifier missing: {_import_error}")

        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "work_platform-0.1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("work_platform/__init__.py", "__version__ = '0.1.0'\n")

            self.assertTrue(verify_distribution(wheel))

    def test_version_reports_both_shas(self):
        self.assertIsNotNone(build_version_report, f"version reporter missing: {_import_error}")

        work_sha = "1" * 40
        octop_sha = "2" * 40
        report = build_version_report(work_sha, octop_sha)

        self.assertEqual(report["source"]["work_sha"], work_sha)
        self.assertEqual(report["source"]["octop_sha"], octop_sha)


if __name__ == "__main__":
    unittest.main()
