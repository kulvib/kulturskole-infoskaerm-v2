from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
UPDATER_SERVICE = ROOT / "client/systemd/clientflow-updater.service"
UPDATER_TIMER = ROOT / "client/systemd/clientflow-updater.timer"


def _unit_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_pending_fresh_install_does_not_execute_updater_before_active_release() -> None:
    """The stable updater host may exist while pending, but updater execution may not.

    Backend update authentication intentionally rejects claim-created update credentials
    until the client is manually approved. First local activation already proves backend
    approval before mutating /opt/clientflow/active. Therefore the systemd updater service
    must stay gated on the active-release symlink instead of polling backend while the
    installation is in pending_manual_activation.
    """

    lines = _unit_lines(UPDATER_SERVICE)

    assert "ConditionPathExists=/etc/clientflow/update/credential.json" in lines
    assert "ConditionPathExists=/etc/clientflow/update/private-key.pem" in lines
    assert "ConditionPathExists=/opt/clientflow/active" in lines

    exec_line = next(line for line in lines if line.startswith("ExecStart="))
    assert exec_line == (
        "ExecStart=/usr/bin/python3 -I "
        "/usr/lib/clientflow/updater/clientflow-updater.pyz"
    )


def test_updater_timer_remains_separate_and_polling_after_activation() -> None:
    """Do not regress the canonical stable update plane while fixing pending lifecycle."""

    lines = _unit_lines(UPDATER_TIMER)

    assert "Unit=clientflow-updater.service" in lines
    assert "OnActiveSec=30s" in lines
    assert "OnUnitActiveSec=1min" in lines
    assert "WantedBy=timers.target" in lines


def test_updater_systemd_units_verify_when_systemd_analyze_is_available() -> None:
    """Exercise the actual systemd parser in CI where systemd-analyze is installed."""

    systemd_analyze = shutil.which("systemd-analyze")
    if systemd_analyze is None:
        pytest.skip("systemd-analyze is not installed in this test environment")

    result = subprocess.run(
        [
            systemd_analyze,
            "verify",
            str(UPDATER_SERVICE),
            str(UPDATER_TIMER),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
