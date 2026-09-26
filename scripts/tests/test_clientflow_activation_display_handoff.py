from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISPLAY_RUNTIME = ROOT / "client/runtime/clientflow_runtime/display_runtime.py"
CLIENTS = ROOT / "backend/service1/routers/clients.py"
API = ROOT / "frontend/src/api/api.js"
CLIENT_INFO = ROOT / "frontend/src/pages/ClientInfoPage.jsx"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_display_runtime_adopts_existing_preactivation_gui_instead_of_starting_second_window() -> None:
    source = _source(DISPLAY_RUNTIME)
    compile(source, str(DISPLAY_RUNTIME), "exec")
    assert 'PREACTIVATION_GUI_STATUS_PATH = Path("/var/lib/clientflow/preactivation-gui/local-gui-status.json")' in source
    assert "def _handoff_gui_process(self)" in source
    assert 'if "client-runtime/libexec/local-gui" not in cmdline:' in source
    assert "def _gui_available(self)" in source
    start = source[source.index("def start_local_gui"):source.index("def stop_local_gui")]
    assert "handoff_pid = self._handoff_gui_process()" in start
    assert '"handoff_running": True' in start
    run = source[source.index("def run(self)"):source.index("def main()") ]
    assert 'self.configuration.get("kiosk_url") and self._gui_available()' in run
    assert 'if not self._gui_available() and time.monotonic() >= self.next_gui_start_attempt:' in run


def test_backend_approval_seeds_durable_display_configuration_before_approved_state() -> None:
    source = _source(CLIENTS)
    model = source[source.index("class ClientApprovalRequest"):source.index("EXPECTED_CLIENT_TIMEZONE")]
    assert "kiosk_url: Optional[str] = None" in model
    block = source[source.index("async def approve_client"):source.index("def _generate_client_secret")]
    assert "set_display_desired_kiosk_url(" in block
    assert "Kiosk URL skal angives før klienten kan godkendes" in block
    assert block.index("set_display_desired_kiosk_url(") < block.index('client.status = "approved"')
    assert '"display_configuration_seeded": True' in block


def test_frontend_approval_requires_and_transports_kiosk_url_atomically() -> None:
    api = _source(API)
    page = _source(CLIENT_INFO)
    assert "export async function approveClient(id, organization_id, kiosk_url)" in api
    assert "JSON.stringify({ organization_id, kiosk_url })" in api
    assert "const [kioskUrlSelections, setKioskUrlSelections] = useState({});" in page
    assert 'showSnackbar("Angiv Kiosk URL før klienten godkendes.", "warning")' in page
    assert "await approveClient(clientId, organizationId, kioskUrl)" in page
    assert 'placeholder="https://…"' in page
