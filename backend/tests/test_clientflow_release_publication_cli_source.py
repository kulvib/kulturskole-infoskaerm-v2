from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_publication_cli_resolves_repo_local_release_format_without_ambient_pythonpath(
    tmp_path: Path,
) -> None:
    script = ROOT / "scripts" / "publish_clientflow_release.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Publish one approved ClientFlow runtime-release artifact" in result.stdout
