from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = ROOT / "client" / "systemd"


def test_enabled_clientflow_target_boot_graph_has_no_ordering_cycle(tmp_path: Path) -> None:
    analyzer = shutil.which("systemd-analyze")
    assert analyzer is not None, "systemd-analyze is required for the ClientFlow boot-graph contract"

    unit_root = tmp_path / "systemd"
    wants_root = unit_root / "multi-user.target.wants"
    wants_root.mkdir(parents=True)

    sources = sorted(SYSTEMD_ROOT.glob("clientflow*"))
    assert sources, "ClientFlow systemd definitions are missing"
    for source in sources:
        assert source.is_file() and not source.is_symlink(), f"Invalid ClientFlow unit source: {source}"
        shutil.copy2(source, unit_root / source.name)

    (wants_root / "clientflow.target").symlink_to(Path("../clientflow.target"))

    env = os.environ.copy()
    env["SYSTEMD_UNIT_PATH"] = (
        f"{unit_root}:/etc/systemd/system:/usr/lib/systemd/system:/lib/systemd/system"
    )
    result = subprocess.run(
        [analyzer, "verify", "clientflow.target"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        timeout=60,
        check=False,
    )

    output = result.stdout
    lowered = output.lower()
    assert "ordering cycle" not in lowered, output
    assert "deleted to break ordering cycle" not in lowered, output
    assert result.returncode == 0, output
