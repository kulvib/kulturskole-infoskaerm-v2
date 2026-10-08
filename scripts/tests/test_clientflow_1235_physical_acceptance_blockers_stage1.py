from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_1334_1235_stage1_history_is_preserved_after_exact_release_promotion() -> None:
    assert read("client/VERSION").strip() == "1.3.34"
    release_input = json.loads(read("client/release/release-input.json"))
    assert release_input["release_sequence"] == 1235
    historical_stage = read("CLIENTFLOW_1.3.34_1235_PHYSICAL_ACCEPTANCE_BLOCKERS_STAGE1.md")
    assert "staged source identity only" in historical_stage
    assert "Not source-frozen" in historical_stage

    catalog = json.loads(read("backend/service1/clientflow_release_catalog.json"))
    assert catalog["catalog_sequence"] == 1235
    assert catalog["latest_stable"] == "1.3.34"
    assert catalog["default_install_version"] == "1.3.34"
    assert len(catalog["releases"]) == 1
    assert catalog["releases"][0]["release_id"] == "clientflow-1.3.34-seq-1235"
    assert catalog["releases"][0]["install_modes"] == ["fresh_install"]
    assert catalog["releases"][0]["update_allowed"] is False


def test_local_gui_cannot_be_closed_by_kiosk_user_and_runtime_still_supervises_it() -> None:
    gui = read("client/libexec/local-gui")
    runtime = read("client/runtime/clientflow_runtime/display_runtime.py")

    assert "self.set_deletable(False)" in gui
    assert 'self.connect("close-request", self._keep_open_on_close)' in gui
    assert "def _keep_open_on_close" in gui
    assert "self.present()" in gui
    assert "return True" in gui

    # Process-level recovery remains authoritative if the GUI exits/crashes for
    # a reason other than a user close request.
    assert "local_gui_exited" in runtime
    assert "next_gui_start_attempt = time.monotonic() + 2.0" in runtime
    assert "if not self._local_gui_running()" in runtime
    assert "self.start_local_gui()" in runtime


def test_os_update_projection_exposes_exact_system_command_identity_without_new_db_authority() -> None:
    control = read("backend/service1/system_control.py")
    models = read("backend/service1/models.py")
    clients = read("backend/service1/routers/clients.py")

    assert '"ubuntu_update_command_id": None' in control
    assert '"ubuntu_update_command_id": row.id' in control
    assert "ubuntu_update_command_id: Optional[str] = None" in models
    assert '"ubuntu_update_command_id": getattr(client, "ubuntu_update_command_id", None)' in clients
