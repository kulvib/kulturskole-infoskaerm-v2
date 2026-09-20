from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRESH = ROOT / "client/bootstrap/clientflow-fresh-install"
GUI = ROOT / "client/libexec/local-gui"
TARGET = ROOT / "client/systemd/clientflow.target"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pending_gui_is_a_separate_temporary_service_not_full_runtime() -> None:
    source = _source(FRESH)
    assert 'PREACTIVATION_GUI_SERVICE = "clientflow-preactivation-gui.service"' in source
    assert 'ExecStart=/usr/local/lib/clientflow-bootstrap/clientflow-fresh-install --preactivation-gui' in source
    assert 'Before=clientflow.target' in source
    assert 'Conflicts=clientflow.target' in source
    assert 'WantedBy=multi-user.target' in source
    assert '[str(SYSTEMCTL), "enable", PREACTIVATION_GUI_SERVICE]' in source
    assert 'NoNewPrivileges=yes' in source
    assert 'ProtectSystem=full' in source
    assert 'ProtectKernelTunables=yes' in source
    assert 'CapabilityBoundingSet=CAP_CHOWN CAP_SETGID CAP_SETUID CAP_DAC_READ_SEARCH' in source
    assert 'RestrictAddressFamilies=AF_UNIX AF_NETLINK' in source
    assert 'ProtectHome=' not in source[source.index('def _install_preactivation_gui_service'):source.index('def _ensure_preactivation_gui_started')]
    install_block = source[source.index("def _install_preactivation_gui_service"):source.index("def _ensure_preactivation_gui_started")]
    assert 'CAP_DAC_OVERRIDE' not in install_block
    assert '"--now"' not in install_block

    target = _source(TARGET)
    assert "clientflow-preactivation-gui.service" not in target
    assert "clientflow-terminal-agent.service" in target
    assert "clientflow-remote-desktop-agent.service" in target
    assert "clientflow-livestream" in target


def test_pending_gui_execs_exact_staged_gui_as_unprivileged_kiosk_user() -> None:
    source = _source(FRESH)
    block = source[source.index("def _preactivation_gui"):source.index("def _install_preactivation_gui_service")]
    assert 'release_root / "client-runtime/libexec/local-gui"' in block
    assert 'release_root / "VERSION"' in block
    assert 'os.path.lexists("/opt/clientflow/active")' in source
    assert '"CLIENTFLOW_GUI_MODE": "preactivation"' in block
    assert '"CLIENTFLOW_VERSION_PATH": str(version_path)' in block
    assert '"GDK_BACKEND": "wayland"' in block
    assert '"WAYLAND_DISPLAY": wayland_socket.name' in block
    assert '"CLIENTFLOW_GUI_STATUS_PATH": str(gui_root / "local-gui-status.json")' in block
    assert '"CLIENTFLOW_DISPLAY_RUNTIME_SOCKET": str(gui_root / "no-runtime.sock")' in block
    assert 'str(runtime_dir / "clientflow-preactivation' not in block
    assert 'os.initgroups(KIOSK_USER, account.pw_gid)' in block
    assert 'os.setgid(account.pw_gid)' in block
    assert 'os.setuid(account.pw_uid)' in block
    assert block.index('os.setuid(account.pw_uid)') < block.index('os.execve(')
    assert 'os.execve(str(SYSTEM_PYTHON), [str(SYSTEM_PYTHON), str(local_gui)], environment)' in block


def test_customer_flow_installs_pending_gui_before_reboot_and_cleans_it_after_activation() -> None:
    source = _source(FRESH)
    customer = source[source.index("def _customer_install"):source.index("def main")]
    assert customer.index("_prepare_pre_activation_graphical_session()") < customer.index("_install_preactivation_gui_service()")
    assert customer.index("_install_preactivation_gui_service()") < customer.index("_install_activation_waiter()")
    assert customer.index("_install_activation_waiter()") < customer.index("confirmed_reboot(")
    cleanup = source[source.index("def _cleanup_completed_bootstrap"):source.index("def _activation_wait")]
    assert "_disable_preactivation_gui(remove_unit=True)" in cleanup
    wait = source[source.index("def _activation_wait"):source.index("def _factory_identity")]
    assert "_ensure_preactivation_gui_started()" in wait


def test_same_legacy_layout_gui_has_strict_status_only_pending_mode() -> None:
    source = _source(GUI)
    compile(source, str(GUI), "exec")
    for section in (
        '_frame("Handlinger")',
        '_frame("Systeminfo")',
        '_frame("Kioskinfo")',
        '_frame("Netværksinfo")',
        '_frame("Kalender – næste 7 dage")',
    ):
        assert section in source
    assert 'GUI_MODE = str(os.getenv("CLIENTFLOW_GUI_MODE") or "active").strip().lower()' in source
    assert 'PREACTIVATION_MODE = GUI_MODE == "preactivation"' in source
    assert 'VERSION_PATH = Path(os.getenv("CLIENTFLOW_VERSION_PATH", "/opt/clientflow/active/VERSION"))' in source
    assert '"Registreret / afventer godkendelse"' in source
    assert '"Registreret – afventer godkendelse"' in source
    assert 'self._set(key, "Ikke aktiveret", COLOR_GRAY)' in source
    assert 'self.start_button.set_sensitive(False)' in source
    assert 'self.stop_button.set_sensitive(False)' in source
    send_action = source[source.index("def _send_action"):source.index("def refresh")]
    assert send_action.index("if PREACTIVATION_MODE:") < send_action.index("_rpc(payload")
    assert 'Gtk.Button(label="Skift til administrator")' not in source
    assert "SWITCH_USER_HELPER" not in source
