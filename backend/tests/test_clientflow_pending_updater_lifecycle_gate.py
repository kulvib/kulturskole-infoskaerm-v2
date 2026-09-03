from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release import transaction  # noqa: E402
from clientflow_release.transaction import Layout  # noqa: E402


def test_stable_updater_service_remains_independent_of_active_release() -> None:
    service = (ROOT / "client/systemd/clientflow-updater.service").read_text(
        encoding="utf-8"
    )

    # Stable updater is a release-independent bootstrap plane.  Pending gating
    # belongs to installer/transaction lifecycle, not to the service definition.
    assert "/opt/clientflow/active" not in service
    assert "User=clientflow-updater" in service
    assert (
        "ExecStart=/usr/bin/python3 -I "
        "/usr/lib/clientflow/updater/clientflow-updater.pyz"
    ) in service
    assert "OnSuccess=clientflow-update-controller.service" in service


def test_pending_lifecycle_disables_timer_without_changing_updater_service(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        calls.append(command)
        return None

    monkeypatch.setattr(transaction, "_run", fake_run)

    transaction._disable_stable_updater_timer(Layout())

    assert calls == [
        [
            "/usr/bin/systemctl",
            "disable",
            "--now",
            "clientflow-updater.timer",
        ]
    ]
