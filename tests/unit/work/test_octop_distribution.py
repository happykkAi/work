"""The Octop distribution must start without a source-tree Work package."""

import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def test_octop_artifacts_include_required_work_modules(tmp_path):
    root = Path(__file__).resolve().parents[3]
    built = subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path / "dist")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    wheel = next((tmp_path / "dist").glob("octop-*.whl"))
    package_dir = tmp_path / "packages"
    with zipfile.ZipFile(wheel) as archive:
        assert "work_platform/authorization.py" in archive.namelist()
        archive.extractall(package_dir)
    sdist = next((tmp_path / "dist").glob("octop-*.tar.gz"))
    with tarfile.open(sdist) as archive:
        assert any(
            name.endswith("packages/work_platform/src/work_platform/authorization.py")
            for name in archive.getnames()
        )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); import work_platform; "
            "assert Path(work_platform.__file__).is_relative_to(Path(sys.argv[1])); "
            "from octop.infra.server import OctopServer; "
            "from octop.launch import run_foreground_blocking; print('startup-import-ok')",
            str(package_dir),
        ],
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "startup-import-ok"
