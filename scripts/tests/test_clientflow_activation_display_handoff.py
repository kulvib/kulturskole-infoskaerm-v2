from __future__ import annotations

import json
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release.transaction import (  # noqa: E402
    Layout,
    _commit_first_activation_gui_handoff,
    _remove_first_activation_gui_handoff,
    _write_first_activation_gui_handoff,
)


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_approval_handoff_keeps_pending_gui_process_alive() -> None:
    fresh = _source("client/bootstrap/clientflow-fresh-install")
    install = fresh[
        fresh.index("def _install_preactivation_gui_service") : fresh.index(
            "def _ensure_preactivation_gui_started"
        )
    ]
    cleanup = fresh[
        fresh.index("def _cleanup_completed_bootstrap") : fresh.index(
            "def _activation_wait"
        )
    ]

    assert "Before=clientflow.target" in install
    assert "Conflicts=clientflow.target" not in install
    assert "_disable_preactivation_gui(remove_unit=True, preserve_running=True)" in cleanup


def test_first_activation_handoff_is_root_controlled_and_rollback_revokes_it() -> None:
    transaction = _source("client/release/lib/clientflow_release/transaction.py")
    assert 'FIRST_ACTIVATION_GUI_HANDOFF = "/run/clientflow/preactivation-gui-handoff.json"' in transaction
    assert "_write_first_activation_gui_handoff(layout, release_id)" in transaction
    assert "_commit_first_activation_gui_handoff(layout, release_id)" in transaction
    assert "_retire_preserved_first_activation_gui_before_update(layout)" in transaction
    failure = transaction[
        transaction.index("except Exception as activation_error:") : transaction.index(
            'return {"status": "active"'
        )
    ]
    assert failure.index("_remove_first_activation_gui_handoff(layout)") < failure.index(
        "_restore_pending_first_activation"
    )

    gui = _source("client/libexec/local-gui")
    assert "metadata.st_uid != 0" in gui
    assert "metadata.st_mode & 0o022" in gui
    assert "ACTIVE_ROOT.resolve(strict=True)" in gui
    assert 'Path(str(_ACTIVE_PATHS["socket"])).exists()' in gui


def test_display_runtime_adopts_existing_gui_before_spawning_replacement() -> None:
    runtime = _source("client/runtime/clientflow_runtime/display_runtime.py")
    startup = runtime[runtime.index("def run(self)") : runtime.index("def main()")]
    assert "def _adopt_preactivation_gui" in runtime
    assert "self.external_local_gui_pid: int | None = None" in runtime
    assert startup.index("if not self._adopt_preactivation_gui():") < startup.index(
        "self.start_local_gui()"
    )
    assert "_pid_is_expected_local_gui" in runtime


def test_approval_can_commit_display_desired_state_before_client_becomes_approved() -> None:
    clients = _source("backend/service1/routers/clients.py")
    approval = clients[
        clients.index("async def approve_client(") : clients.index("def _generate_client_secret")
    ]
    assert "kiosk_url: Optional[str] = None" in clients
    assert '"kiosk_url" in data.model_fields_set' in approval
    assert "set_display_desired_kiosk_url(" in approval
    assert approval.index("set_display_desired_kiosk_url(") < approval.index(
        'client.status = "approved"'
    )
    assert '"kiosk_url_after"' in approval


def test_pending_approval_ui_sends_kiosk_url_with_organization() -> None:
    api = _source("frontend/src/api/api.js")
    page = _source("frontend/src/pages/ClientInfoPage.jsx")
    contract = _source("frontend/tests/contracts/clientflowFrontendBackendContract.json")

    assert "export async function approveClient(id, organization_id, kiosk_url)" in api
    assert "if (kiosk_url !== undefined) payload.kiosk_url = kiosk_url" in api
    assert 'label="Kiosk URL (valgfri)"' in page
    assert "await approveClient(clientId, organizationId, kioskUrl || undefined)" in page
    assert '"organization_id",\n        "kiosk_url"' in contract


def test_handoff_marker_writer_is_atomic_mode_0644_and_exact_release_bound(tmp_path: Path) -> None:
    layout = Layout(root=tmp_path)
    release_id = "clientflow-1.3.26-seq-1227"
    _write_first_activation_gui_handoff(layout, release_id)

    marker = tmp_path / "run/clientflow/preactivation-gui-handoff.json"
    metadata = marker.lstat()
    assert stat.S_ISREG(metadata.st_mode)
    assert stat.S_IMODE(metadata.st_mode) == 0o644
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["state"] == "activating"
    assert payload["release_id"] == release_id
    assert payload["authorized_at"]

    _commit_first_activation_gui_handoff(layout, release_id)
    committed = json.loads(marker.read_text(encoding="utf-8"))
    assert committed["state"] == "committed"
    assert committed["release_id"] == release_id
    assert committed["committed_at"]

    _remove_first_activation_gui_handoff(layout)
    assert not marker.exists()
