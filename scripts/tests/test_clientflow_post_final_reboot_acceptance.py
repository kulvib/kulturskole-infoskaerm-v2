from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "client" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from clientflow_runtime import post_final_reboot_acceptance as gate


def _pending(state_path: Path, boot_id: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "schema_version": 1,
        "status": "awaiting_post_final_reboot_acceptance",
        "pre_reboot_boot_id": boot_id,
        "lockdown_verified_before_reboot": True,
    }), encoding="utf-8")
    state_path.chmod(0o600)


def test_post_final_reboot_gate_rejects_same_boot(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "customer-handoff.json"
    boot_path = tmp_path / "boot_id"
    boot_path.write_text("boot-a\n", encoding="ascii")
    _pending(state_path, "boot-a")
    monkeypatch.setattr(gate, "STATE_PATH", state_path)
    monkeypatch.setattr(gate, "BOOT_ID_PATH", boot_path)
    monkeypatch.setattr(gate, "STATE_OWNER_UID", state_path.stat().st_uid)
    monkeypatch.setattr(gate.os, "geteuid", lambda: 0)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="Final reboot"):
        gate.verify_and_accept()


def test_post_final_reboot_gate_accepts_only_verified_new_boot(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "customer-handoff.json"
    boot_path = tmp_path / "boot_id"
    boot_path.write_text("boot-b\n", encoding="ascii")
    nautilus = tmp_path / "nautilus"
    nautilus.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    nautilus.chmod(0o755)
    _pending(state_path, "boot-a")
    monkeypatch.setattr(gate, "STATE_PATH", state_path)
    monkeypatch.setattr(gate, "BOOT_ID_PATH", boot_path)
    monkeypatch.setattr(gate, "NAUTILUS", nautilus)
    monkeypatch.setattr(gate, "STATE_OWNER_UID", state_path.stat().st_uid)
    monkeypatch.setattr(gate.os, "geteuid", lambda: 0)
    monkeypatch.setattr(gate, "_active_local_kiosk_session", lambda: "session-1")
    monkeypatch.setattr(gate, "lockdown_status", lambda: {
        "desired": True, "status": "applied", "enforcement": {"ok": True}
    })
    monkeypatch.setattr(gate, "_group_names", lambda username: {"sudo"} if username == "cfadmin" else set())

    result = gate.verify_and_accept()
    assert result["status"] == "accepted"
    assert result["accepted_boot_id"] == "boot-b"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "accepted"
    assert persisted["kiosk_lockdown_status"] == "applied"
    assert persisted["kiosk_session_ready"] is True
    assert persisted["nautilus_ready"] is True
    assert persisted["account_separation_ready"] is True

def test_post_final_reboot_gate_rejects_wrong_state_owner(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "customer-handoff.json"
    _pending(state_path, "boot-a")
    monkeypatch.setattr(gate, "STATE_PATH", state_path)
    monkeypatch.setattr(gate, "STATE_OWNER_UID", state_path.stat().st_uid + 1)
    monkeypatch.setattr(gate.os, "geteuid", lambda: 0)
    with pytest.raises(gate.PostFinalRebootAcceptanceError, match="ownership/permissions"):
        gate.verify_and_accept()

