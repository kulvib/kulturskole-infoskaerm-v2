from __future__ import annotations

import fcntl
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLIENT_RUNTIME = ROOT / "client/runtime"
if str(CLIENT_RUNTIME) not in sys.path:
    sys.path.insert(0, str(CLIENT_RUNTIME))

from clientflow_runtime import system_broker  # noqa: E402


LEGACY_RELEASE_ACTIONS = ("update_clientflow", "activate_release", "rollback_release")


def test_system_broker_has_no_parallel_clientflow_release_authority(monkeypatch):
    assert system_broker.ALLOWED_ACTIONS == {
        "update_os",
        "reboot",
        "shutdown",
        "change_hostname",
        "change_password",
    }

    monkeypatch.setattr(system_broker, "_fixed_binary", lambda name: f"/usr/bin/{name}")
    command_id = "00000000-0000-4000-8000-000000000001"
    for action in LEGACY_RELEASE_ACTIONS:
        with pytest.raises(ValueError, match="ikke implementeret"):
            system_broker._prepare(action, {}, client_id=42, command_id=command_id)


def test_system_broker_retains_reboot_and_shutdown_fixed_function_contract(monkeypatch):
    monkeypatch.setattr(system_broker, "_fixed_binary", lambda name: f"/usr/bin/{name}")
    command_id = "00000000-0000-4000-8000-000000000001"

    assert system_broker._prepare("reboot", {}, client_id=42, command_id=command_id) == {
        "command": ["/usr/bin/systemctl", "--no-block", "reboot"],
        "timeout": 10,
    }
    assert system_broker._prepare("shutdown", {}, client_id=42, command_id=command_id) == {
        "command": ["/usr/bin/systemctl", "--no-block", "poweroff"],
        "timeout": 10,
    }


def _bind_temp_journal(monkeypatch, tmp_path, *, boot_id: str) -> None:
    state_dir = tmp_path / "system-broker"
    monkeypatch.setattr(system_broker, "STATE_DIR", state_dir)
    monkeypatch.setattr(system_broker, "JOURNAL_PATH", state_dir / "command-journal.json")
    monkeypatch.setattr(system_broker, "JOURNAL_LOCK_PATH", state_dir / "command-journal.lock")
    boot_id_path = tmp_path / "boot_id"
    boot_id_path.write_text(boot_id + "\n", encoding="ascii")
    monkeypatch.setattr(system_broker, "BOOT_ID_PATH", boot_id_path)


@pytest.mark.parametrize("action", ["reboot", "shutdown"])
def test_system_broker_recovers_disruptive_command_after_observed_boot_change(
    monkeypatch, tmp_path, action
):
    first_boot = "11111111-1111-4111-8111-111111111111"
    second_boot = "22222222-2222-4222-8222-222222222222"
    _bind_temp_journal(monkeypatch, tmp_path, boot_id=first_boot)
    command_id = "00000000-0000-4000-8000-000000000099"

    lock_fd, completed = system_broker._journal_begin(42, command_id, action)
    assert completed is None
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    os.close(lock_fd)

    system_broker.BOOT_ID_PATH.write_text(second_boot + "\n", encoding="ascii")
    lock_fd, completed = system_broker._journal_begin(42, command_id, action)
    try:
        assert completed == {
            "exit_code": 0,
            "recovered_after_boot_change": True,
            "previous_boot_id": first_boot,
            "observed_boot_id": second_boot,
        }
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    journal = system_broker._load_journal()
    entry = journal[f"42:{command_id}"]
    assert entry["state"] == "completed"
    assert entry["result"] == completed


def test_system_broker_same_boot_keeps_disruptive_command_in_doubt(monkeypatch, tmp_path):
    boot_id = "11111111-1111-4111-8111-111111111111"
    _bind_temp_journal(monkeypatch, tmp_path, boot_id=boot_id)
    command_id = "00000000-0000-4000-8000-000000000098"

    lock_fd, completed = system_broker._journal_begin(42, command_id, "reboot")
    assert completed is None
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    os.close(lock_fd)

    with pytest.raises(system_broker.SystemCommandInDoubt, match="system_command_in_doubt"):
        system_broker._journal_begin(42, command_id, "reboot")


def test_system_broker_boot_change_never_auto_completes_non_disruptive_action(
    monkeypatch, tmp_path
):
    first_boot = "11111111-1111-4111-8111-111111111111"
    second_boot = "22222222-2222-4222-8222-222222222222"
    _bind_temp_journal(monkeypatch, tmp_path, boot_id=first_boot)
    command_id = "00000000-0000-4000-8000-000000000097"

    lock_fd, completed = system_broker._journal_begin(42, command_id, "change_hostname")
    assert completed is None
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    os.close(lock_fd)

    system_broker.BOOT_ID_PATH.write_text(second_boot + "\n", encoding="ascii")
    with pytest.raises(system_broker.SystemCommandInDoubt, match="system_command_in_doubt"):
        system_broker._journal_begin(42, command_id, "change_hostname")
