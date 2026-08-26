from __future__ import annotations

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
