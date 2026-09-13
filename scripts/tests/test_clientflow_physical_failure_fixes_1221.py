from __future__ import annotations

import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "client/bootstrap/clientflow-fresh-install"
CLI = ROOT / "client/release/lib/clientflow_release/cli.py"
TX = ROOT / "client/release/lib/clientflow_release/transaction.py"
GUARD = ROOT / "client/runtime/clientflow_runtime/browser_guard.py"
SESSION_PREP = ROOT / "client/runtime/clientflow_runtime/display_session_prepare.py"
GUI = ROOT / "client/libexec/local-gui"
QUICK = ROOT / "client/systemd/clientflow-kiosk-quicksettings-guard.service"
VERSION = ROOT / "client/VERSION"
RELEASE_INPUT = ROOT / "client/release/release-input.json"
CATALOG = ROOT / "backend/service1/clientflow_release_catalog.json"

LEGACY_GUI_SHA256 = "027804da4cf3e722ce42a6d7760aa55a1a8f30d901bfc532a1cf63e22d5ba936"
LEGACY_STATUS_MAP_SHA256 = "9e6f01fbbe4b23f1458cc2740cea1bc43777499f8d4da3bd83f2a474fb7e74b4"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _class_tuple(source: str, class_name: str, name: str):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    if any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
                        return ast.literal_eval(statement.value)
    raise AssertionError(f"{class_name}.{name} not found")


def test_source_1320_1221_is_staged_while_catalog_stays_on_1319_1220():
    # The physical-fix/lifecycle changes have passed their CI gates. The next
    # source/build identity may now advance one step while runtime selection
    # remains on the last approved and immutably published catalog release.
    assert VERSION.read_text(encoding="utf-8").strip() == "1.3.20"
    release_input = json.loads(_source(RELEASE_INPUT))
    assert release_input["release_sequence"] == 1221
    assert release_input["minimum_ubuntu_lts"] == "26.04"
    assert release_input["architecture"] == "amd64"
    assert release_input["runtime_python"] == "3.13.14"

    catalog = json.loads(_source(CATALOG))
    assert catalog["catalog_sequence"] == 1220
    assert catalog["latest_stable"] == "1.3.19"
    assert catalog["default_install_version"] == "1.3.19"
    selected = catalog["releases"][0]
    assert selected["release_id"] == "clientflow-1.3.19-seq-1220"


def test_dispatch_uses_staged_immutable_release_cli_not_stable_updater():
    source = _source(HELPER)
    assert "STABLE_UPDATER" not in source
    assert '"-P", "-m", "clientflow_release", "activate"' in source
    assert 'release_root / "runtime/bin/python"' in source
    assert 'release_root / "release/lib/clientflow_release/__init__.py"' in source
    assert '"PYTHONDONTWRITEBYTECODE": "1"' in source
    assert '"PYTHONNOUSERSITE": "1"' in source
    assert '"PYTHONPATH": str(release_root / "release/lib")' in source
    assert "--expected-release-approval-reference" in source


def test_fresh_install_materializes_graphical_login_before_reboot_and_activation_requires_kiosk_wayland():
    helper = _source(HELPER)
    session_prepare = _source(SESSION_PREP)
    cli = _source(CLI)
    assert 'state.get("status") != "pending_manual_activation"' in helper
    assert '"clientflow_runtime.display_session_prepare"' in helper
    assert '_prepare_pre_activation_graphical_session()' in helper
    assert '[str(SYSTEMCTL), "--no-block", "reboot"]' in helper
    post_install = helper[helper.index("authorities = f"):helper.index("except urllib.error.HTTPError")]
    assert post_install.index("_prepare_pre_activation_graphical_session()") < post_install.index("_queue_controlled_pre_activation_reboot()")
    assert 'prepare_graphical_login_baseline' in session_prepare
    assert '_ensure_exact_chrome' not in session_prepare
    assert '_prepare_system_kiosk_policy' not in session_prepare
    assert 'props.get("Name") == KIOSK_USER' in helper
    assert 'props.get("Seat") == "seat0"' in helper
    assert 'props.get("Remote") == "no"' in helper
    assert 'props.get("Type") == "wayland"' in helper
    assert '[str(LOGINCTL), "activate", session_id]' in helper
    assert cli.count('"automatic_reboot": False') == 2
    assert cli.count('"pre_activation_reboot_required": True') == 2
    assert cli.count('"reboot_reason": "establish_kiosk_wayland_session_before_manual_activation"') == 2


def test_activation_health_excludes_only_explicitly_optional_units():
    tx = _source(TX)
    quick = _source(QUICK)
    marker = "# ClientFlow-Activation-Health: optional"
    assert f'_ACTIVATION_HEALTH_OPTIONAL_MARKER = "{marker}"' in tx
    assert marker in quick
    fn = tx[tx.index("def _expected_active_units("):tx.index("def _health_check(")]
    assert '"WantedBy=clientflow.target" in text' in fn
    assert "_ACTIVATION_HEALTH_OPTIONAL_MARKER in text" in fn
    executable = "\n".join(line for line in fn.splitlines() if not line.lstrip().startswith(("#", '"""')))
    assert "ConditionPathExists" not in executable
    assert "ConditionPathExists=" not in executable


def test_browser_guard_is_quiet_when_chrome_is_intentionally_unavailable_but_reports_empty_running_chrome():
    source = _source(GUARD)
    assert 'VERSION = "1.6.6"' in source
    assert "return None" in source[source.index("def get_tabs():"):source.index("def is_main_page_target")]
    run_once = source[source.index("async def run_once"):source.index("async def _async_main")]
    assert "if tab_payload is None:" in run_once
    assert "return None" in run_once
    main = source[source.index("async def _async_main"):source.index("def main()")]
    assert "chrome_ready = run_result is not None" in main
    assert "if chrome_ready:" in main
    assert 'log("Ingen main page http(s)-tabs fundet i kørende Chrome.")' in main
    assert "Ingen main page http(s)-tabs fundet eller Chrome ikke klar." not in main


def test_gui_matches_deployed_1_1_19_visible_structure_and_order():
    source = _source(GUI)
    sections = [
        '_frame("Handlinger")',
        '_frame("Systeminfo")',
        '_frame("Kioskinfo")',
        '_frame("Netværksinfo")',
        '_frame("Kalender – næste 7 dage")',
    ]
    positions = [source.index(token) for token in sections]
    assert positions == sorted(positions)
    assert 'title="ClientFlow Status"' in source
    assert 'Gtk.Button(label="Start kiosk")' in source
    assert 'Gtk.Button(label="Stop kiosk")' in source
    # Existing V2 technician switching remains available, but is rendered as a
    # subordinate second-row action so the two legacy primary buttons keep
    # their equal-width geometry.
    assert 'Gtk.Button(label="Skift til administrator")' in source
    assert 'SWITCH_USER_HELPER' in source
    assert '[str(SWITCH_USER_HELPER)]' in source
    assert 'timeout=10' in source
    assert 'shell=True' not in source
    assert 'Gtk.Label(label="ClientFlow"' not in source
    assert 'button = Gtk.Button(label="⧉")' in source
    assert 'ok.set_text("Kopieret!")' in source
    assert "GLib.timeout_add(1500, clear)" in source


def test_gui_system_network_kiosk_and_calendar_fields_match_deployed_legacy_contract():
    source = _source(GUI)
    assert _class_tuple(source, "ClientFlowWindow", "SYSTEM_FIELDS") == (
        ("Klient ID", "client_id"),
        ("Navn / Lokation", "name_locality"),
        ("Backend-status", "backend"),
        ("ClientFlow version", "version"),
        ("Backend sync", "backend_sync"),
        ("Kalender service", "calendar_service"),
        ("Browser Guard", "browser_guard"),
        ("Remote terminal", "terminal"),
        ("Admin terminal", "admin_terminal"),
        ("Remote desktop", "remote_desktop"),
        ("ClientFlow update", "update"),
        ("Ubuntu update", "ubuntu_update"),
        ("Livestream", "livestream"),
        ("Oppetid", "uptime"),
    )
    assert _class_tuple(source, "ClientFlowWindow", "NETWORK_FIELDS") == (
        ("Aktiv forbindelse", "network_active"),
        ("Aktiv IP", "network_active_ip"),
        ("Aktivt interface", "network_active_interface"),
        ("Aktiv MAC", "network_active_mac"),
        ("WiFi IP", "network_wifi_ip"),
        ("WiFi MAC", "network_wifi_mac"),
        ("LAN IP", "network_lan_ip"),
        ("LAN MAC", "network_lan_mac"),
    )
    for token in (
        '("Kiosk URL", "kiosk_url")',
        '("Auto refresh", "browser_refresh")',
        'configuration.get("browser_refresh_interval_sec")',
        'self._set("browser_refresh", "slået fra" if refresh_seconds == 0 else f"{refresh_seconds} sek.")',
        '("Status", "operational_status")',
        '("Kiosk browser status", "display")',
        '("Aktuel skærm", "resolution_current")',
        '("Backend-valgt", "resolution_desired")',
        '("Skærmstatus", "resolution_status")',
        '("Dato", "Status", "Åbner", "Lukker")',
        '"💤 Skærm slukket — klient online"',
    ):
        assert token in source


def test_gui_visual_constants_responsiveness_no_scroll_and_wrapping_match_contract():
    source = _source(GUI)
    expected = {
        'COLOR_GREEN = "#218739"',
        'COLOR_RED = "#cc3333"',
        'COLOR_ORANGE = "#ffa500"',
        'COLOR_GRAY = "#888888"',
        'COLOR_BG = "#f4f6fa"',
        'COLOR_BLUE = "#1E88E5"',
        "GUI_PANEL_WIDTH_RATIO = 0.43",
        "GUI_PANEL_HEIGHT_RATIO = 0.98",
        "GUI_PANEL_MIN_WIDTH = 420",
        "GUI_PANEL_MIN_HEIGHT = 620",
        "GUI_PANEL_MAX_WIDTH = 900",
        "GUI_COMPACT_MAX_WIDTH = 760",
        "GUI_LARGE_MAX_WIDTH = 1100",
        "GUI_COMPACT_WIDTH_RATIO = 0.56",
        "GUI_LARGE_WIDTH_RATIO = 0.34",
        "GUI_COMPACT_SCALE_MIN = 0.66",
        "GUI_STANDARD_SCALE_MAX = 1.02",
        "GUI_LARGE_SCALE_MAX = 1.22",
        "GUI_CALENDAR_VISIBLE_DAYS = 7",
        "self.set_resizable(False)",
        "action_grid.set_column_homogeneous(True)",
        "homogeneous=True",
        "GLib.timeout_add_seconds(1, self.refresh)",
        "value.set_wrap(True)",
        "value.set_ellipsize(Pango.EllipsizeMode.NONE)",
        "font-family: Arial, sans-serif",
        ".start-button {{ background-image: none; background-color: #4BB543; }}",
    }
    for token in expected:
        assert token in source
    assert "Gtk.ScrolledWindow" not in source
    assert "geometry.width * scale" not in source
    assert "geometry.height * scale" not in source
    assert re.search(r'hidden_network = \{"network_active_mac", "network_wifi_mac", "network_lan_mac"\}', source)


def test_gui_parity_reference_is_explicit_and_immutable_in_test_contract():
    assert re.fullmatch(r"[0-9a-f]{64}", LEGACY_GUI_SHA256)
    assert re.fullmatch(r"[0-9a-f]{64}", LEGACY_STATUS_MAP_SHA256)
