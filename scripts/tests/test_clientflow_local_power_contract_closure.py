from __future__ import annotations

from pathlib import Path
import stat
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "client/runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from clientflow_runtime import power_lifecycle  # noqa: E402


def _configure(monkeypatch, tmp_path: Path, boot_id: str) -> Path:
    state = tmp_path / "power-events"
    boot = tmp_path / "boot_id"
    boot.write_text(boot_id + "\n", encoding="ascii")
    monkeypatch.setattr(power_lifecycle, "STATE_DIR", state)
    monkeypatch.setattr(power_lifecycle, "LOCAL_MARKER_PATH", state / "local-transition.json")
    monkeypatch.setattr(power_lifecycle, "SYSTEM_INTENT_PATH", state / "system-command-intent.json")
    monkeypatch.setattr(power_lifecycle, "BOOT_ID_PATH", boot)
    return boot


def test_local_reboot_marker_survives_boot_and_becomes_status_evidence(monkeypatch, tmp_path: Path):
    previous = str(uuid.uuid4())
    current = str(uuid.uuid4())
    boot = _configure(monkeypatch, tmp_path, previous)

    marker = power_lifecycle.mark_local_transition("reboot")
    assert marker["source"] == "local"
    assert marker["previous_boot_id"] == previous
    mode = stat.S_IMODE(power_lifecycle.LOCAL_MARKER_PATH.stat().st_mode)
    assert mode == 0o644
    assert power_lifecycle.collect_completed_local_power_event() is None

    boot.write_text(current + "\n", encoding="ascii")
    event = power_lifecycle.collect_completed_local_power_event()
    assert event is not None
    assert event["event"] == "reboot_completed"
    assert event["action"] == "reboot"
    assert event["source"] == "local"
    assert event["previous_boot_id"] == previous
    assert event["observed_boot_id"] == current


def test_canonical_system_intent_suppresses_false_local_attribution(monkeypatch, tmp_path: Path):
    boot_id = str(uuid.uuid4())
    _configure(monkeypatch, tmp_path, boot_id)
    power_lifecycle.record_system_intent(
        action="shutdown",
        command_id=str(uuid.uuid4()),
        source="control_room",
        requested_boot_id=boot_id,
    )
    result = power_lifecycle.mark_local_transition("shutdown")
    assert result == {"status": "canonical_system_command", "action": "shutdown"}
    assert not power_lifecycle.LOCAL_MARKER_PATH.exists()
    assert not power_lifecycle.SYSTEM_INTENT_PATH.exists()


def test_wrong_action_intent_cannot_mask_local_transition(monkeypatch, tmp_path: Path):
    boot_id = str(uuid.uuid4())
    _configure(monkeypatch, tmp_path, boot_id)
    power_lifecycle.record_system_intent(
        action="reboot",
        command_id=str(uuid.uuid4()),
        source="control_room",
        requested_boot_id=boot_id,
    )
    result = power_lifecycle.mark_local_transition("shutdown")
    assert result["source"] == "local"
    assert result["action"] == "shutdown"
    assert power_lifecycle.LOCAL_MARKER_PATH.is_file()
    assert not power_lifecycle.SYSTEM_INTENT_PATH.exists()


def test_reporter_systemd_units_are_power_target_hooks_not_runtime_services():
    reboot = (ROOT / "client/systemd/clientflow-local-reboot-reporter.service").read_text(encoding="utf-8")
    shutdown = (ROOT / "client/systemd/clientflow-local-shutdown-reporter.service").read_text(encoding="utf-8")
    target = (ROOT / "client/systemd/clientflow.target").read_text(encoding="utf-8")
    transaction = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text(encoding="utf-8")
    wipe = (ROOT / "client/release/lib/clientflow_release/wipe.py").read_text(encoding="utf-8")

    assert "DefaultDependencies=no" in reboot
    assert "Before=reboot.target" in reboot
    assert "WantedBy=reboot.target" in reboot
    assert "clientflow-power-event-marker reboot" in reboot
    assert "Before=poweroff.target halt.target" in shutdown
    assert "WantedBy=poweroff.target halt.target" in shutdown
    assert "clientflow-power-event-marker shutdown" in shutdown
    assert "clientflow-local-reboot-reporter.service" not in target
    assert "clientflow-local-shutdown-reporter.service" not in target
    assert "_enable_power_lifecycle_reporters" in transaction
    assert "_disable_power_lifecycle_reporters" in transaction
    assert "_disable_power_lifecycle_reporters" in wipe


def test_status_and_system_domains_share_only_nonsecret_power_evidence():
    status = (ROOT / "client/runtime/clientflow_runtime/status_agent.py").read_text(encoding="utf-8")
    broker = (ROOT / "client/runtime/clientflow_runtime/system_broker.py").read_text(encoding="utf-8")
    module = (ROOT / "client/runtime/clientflow_runtime/power_lifecycle.py").read_text(encoding="utf-8")

    assert "collect_completed_local_power_event" in status
    assert '"local_power_event"' in status
    assert "record_system_intent(" in broker
    assert "clear_system_intent()" in broker
    assert "DomainCredential" not in module
    assert "/etc/clientflow/credentials" not in module


def test_obsolete_lockdown_control_is_not_exposed_by_frontend():
    info = (ROOT / "frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api/api.js").read_text(encoding="utf-8")

    combined = info + page + api
    assert "Kiosk lockdown" not in combined
    assert "desktop_lockdown_enabled" not in combined
    assert "desktop_lockdown_status" not in combined
    assert "client_update_" not in info


def test_transaction_explicitly_enables_and_disables_power_target_hooks(monkeypatch, tmp_path: Path):
    release_lib = ROOT / "client/release/lib"
    backend_root = ROOT / "backend"
    if str(release_lib) not in sys.path:
        sys.path.insert(0, str(release_lib))
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from clientflow_release import transaction

    unit_root = tmp_path / "systemd"
    unit_root.mkdir()
    for name in transaction._POWER_LIFECYCLE_REPORTER_UNITS:
        (unit_root / name).write_text("[Unit]\nDescription=test\n", encoding="utf-8")

    class FakeLayout:
        root = Path("/")

        def __init__(self, units: Path):
            self.unit_root = units

    calls = []
    monkeypatch.setattr(transaction, "_run", lambda command, **kwargs: calls.append(list(command)))

    transaction._enable_power_lifecycle_reporters(FakeLayout(unit_root))
    assert calls == [
        ["/usr/bin/systemctl", "enable", "clientflow-local-reboot-reporter.service"],
        ["/usr/bin/systemctl", "enable", "clientflow-local-shutdown-reporter.service"],
    ]
    calls.clear()
    transaction._disable_power_lifecycle_reporters(FakeLayout(unit_root))
    assert calls == [
        ["/usr/bin/systemctl", "disable", "clientflow-local-reboot-reporter.service"],
        ["/usr/bin/systemctl", "disable", "clientflow-local-shutdown-reporter.service"],
    ]
