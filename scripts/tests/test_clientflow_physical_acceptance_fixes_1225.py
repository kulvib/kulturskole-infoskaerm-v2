from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRESH = ROOT / "client/bootstrap/clientflow-fresh-install"
BUILDER = ROOT / "client/release/lib/clientflow_release/builder.py"
TRANSACTION_LIB = ROOT / "client/release/lib"
DISPLAY_RUNTIME_ROOT = ROOT / "client/runtime"
DISPLAY_PLATFORM = DISPLAY_RUNTIME_ROOT / "clientflow_runtime/display_platform_prepare.py"
STATUS_AGENT_SERVICE = ROOT / "client/systemd/clientflow-status-agent.service"
LOCAL_GUI = ROOT / "client/libexec/local-gui"

BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(TRANSACTION_LIB) not in sys.path:
    sys.path.insert(0, str(TRANSACTION_LIB))
if str(DISPLAY_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(DISPLAY_RUNTIME_ROOT))

from clientflow_release import builder, transaction  # noqa: E402
from clientflow_release.transaction import Layout  # noqa: E402
from clientflow_runtime import display_runtime, status_agent  # noqa: E402


def _load_display_platform():
    name = "clientflow_display_platform_1225_test"
    spec = importlib.util.spec_from_file_location(name, DISPLAY_PLATFORM)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_staged_local_gui_is_forced_executable_in_release_payload() -> None:
    source = ROOT / "client/libexec/local-gui"
    target = __import__("pathlib").PurePosixPath("clientflow-1.3.25/client-runtime/libexec/local-gui")
    assert source.stat().st_mode & 0o111 == 0  # source ZIP mode must not be authority
    assert "client-runtime/libexec/local-gui" in builder.DIRECT_EXEC_PAYLOAD_SUFFIXES
    assert builder._payload_source_mode(source, target) == 0o755


def test_preactivation_service_has_least_privilege_wayland_traversal_and_safe_xdg_order() -> None:
    source = FRESH.read_text(encoding="utf-8")
    service = source[source.index("def _install_preactivation_gui_service"):source.index("def _ensure_preactivation_gui_started")]
    assert "CapabilityBoundingSet=CAP_CHOWN CAP_SETGID CAP_SETUID CAP_DAC_READ_SEARCH" in service
    assert "CAP_DAC_OVERRIDE" not in service

    gui = source[source.index("def _preactivation_gui"):source.index("def _install_preactivation_gui_service")]
    create_child = 'directory.mkdir(parents=True, exist_ok=True, mode=0o700)'
    reclaim_root = 'for directory in directories:'
    transfer_parent_last = 'for directory in (*xdg.values(), gui_root):'
    assert gui.index(create_child) < gui.index(reclaim_root)
    assert gui.index('os.chown(directory, 0, 0)') < gui.index('os.chmod(directory, 0o700)')
    assert gui.index('os.chmod(directory, 0o700)') < gui.index(transfer_parent_last)
    assert gui.index(transfer_parent_last) < gui.index("os.setuid(account.pw_uid)")
    assert "CAP_FOWNER" not in service


def test_bootstrap_only_units_are_never_release_managed_or_runtime_quiesced(tmp_path: Path) -> None:
    layout = Layout(tmp_path / "root")
    layout.unit_root.mkdir(parents=True)
    for name in (
        "clientflow.target",
        "clientflow-status-agent.service",
        "clientflow-first-activation.service",
        "clientflow-preactivation-gui.service",
        "clientflow-updater.timer",
    ):
        (layout.unit_root / name).write_text("[Unit]\n", encoding="utf-8")

    managed = {path.name for path in transaction._managed_unit_paths(layout)}
    runtime = set(transaction._runtime_unit_names(layout))
    assert "clientflow-first-activation.service" not in managed
    assert "clientflow-preactivation-gui.service" not in managed
    assert "clientflow-first-activation.service" not in runtime
    assert "clientflow-preactivation-gui.service" not in runtime
    assert "clientflow.target" in managed
    assert "clientflow-status-agent.service" in runtime

    transaction._remove_managed_units(layout)
    assert (layout.unit_root / "clientflow-first-activation.service").is_file()
    assert (layout.unit_root / "clientflow-preactivation-gui.service").is_file()


def test_gnome_first_login_and_release_upgrade_markers_are_materialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_display_platform()
    home = tmp_path / "home"
    home.mkdir()
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Ubuntu"\nVERSION_ID="26.04"\n', encoding="utf-8")
    monkeypatch.setattr(module.pwd, "getpwnam", lambda _user: SimpleNamespace(pw_uid=1234, pw_gid=1234))
    monkeypatch.setattr(module.os, "chown", lambda *_args, **_kwargs: None)

    module._prepare_gnome_initial_setup_markers("clientflow-kiosk", home, os_release=os_release)

    first = home / ".config/gnome-initial-setup-done"
    upgrade = home / ".config/gnome-initial-setup/upgrade-26.04-done"
    assert first.read_text(encoding="utf-8") == "yes\n"
    assert upgrade.read_text(encoding="utf-8") == "yes\n"
    assert first.stat().st_mode & 0o777 == 0o600
    assert upgrade.stat().st_mode & 0o777 == 0o600


def test_chrome_first_run_uses_service_owned_xdg_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    profile = state / "browser-profile"
    xdg_root = state / "chrome-xdg"
    monkeypatch.setattr(display_runtime, "STATE_DIR", state)
    monkeypatch.setattr(display_runtime, "PROFILE_DIR", profile)
    monkeypatch.setattr(display_runtime, "CHROME_XDG_ROOT", xdg_root)
    monkeypatch.setattr(display_runtime, "CHROME_XDG_CONFIG", xdg_root / "config")
    monkeypatch.setattr(display_runtime, "CHROME_XDG_CACHE", xdg_root / "cache")
    monkeypatch.setattr(display_runtime, "CHROME_XDG_DATA", xdg_root / "data")
    monkeypatch.setattr(display_runtime, "CHROME_BINARY", Path("/bin/true"))

    runtime = display_runtime.DisplayRuntime.__new__(display_runtime.DisplayRuntime)
    runtime.configuration = {"kiosk_url": "https://example.test/"}
    monkeypatch.setattr(runtime, "_graphical_environment", lambda: {"HOME": "/home/clientflow-kiosk"})
    monkeypatch.setattr(runtime, "_prepare_profile", lambda _url: None)

    _command, environment = runtime._browser_command()
    assert environment["HOME"] == "/home/clientflow-kiosk"
    assert environment["XDG_CONFIG_HOME"] == str(xdg_root / "config")
    assert environment["XDG_CACHE_HOME"] == str(xdg_root / "cache")
    assert environment["XDG_DATA_HOME"] == str(xdg_root / "data")
    for name in ("config", "cache", "data"):
        path = xdg_root / name
        assert path.is_dir()
        assert path.stat().st_mode & 0o777 == 0o700


def test_status_identity_sync_is_credential_bound_and_public_only(tmp_path: Path) -> None:
    target = tmp_path / "client-public.json"
    response = {
        "client_identity": {
            "schema_version": 1,
            "client_id": 42,
            "name": "Viborg4",
            "locality": "Kontoret ved Henrik",
        }
    }
    assert status_agent.sync_public_identity(response, client_id=42, path=target) is True
    value = __import__("json").loads(target.read_text(encoding="utf-8"))
    assert value == response["client_identity"]
    assert target.stat().st_mode & 0o777 == 0o644

    with pytest.raises(RuntimeError, match="matcher ikke status credential"):
        status_agent.sync_public_identity(response, client_id=41, path=target)


def test_status_agent_publishes_non_secret_backend_sync_success(tmp_path: Path) -> None:
    target = tmp_path / "last-success.json"
    status_agent.record_backend_sync_success(client_id=42, path=target, now=1_700_000_000.0)
    payload = __import__("json").loads(target.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "client_id": 42,
        "updated_at": 1_700_000_000.0,
    }
    assert target.stat().st_mode & 0o777 == 0o644
    serialized = target.read_text(encoding="utf-8").lower()
    for forbidden in ("secret", "credential", "token", "private_key", "backend_url"):
        assert forbidden not in serialized


def test_active_gui_prefers_synced_identity_and_status_directory_is_readable() -> None:
    gui = LOCAL_GUI.read_text(encoding="utf-8")
    assert 'SYNCED_PUBLIC_CLIENT_PATH = Path(os.getenv("CLIENTFLOW_SYNCED_PUBLIC_CLIENT_PATH", "/var/lib/clientflow/status/client-public.json"))' in gui
    refresh = gui[gui.index("def refresh"):]
    assert refresh.index("_read_json(PUBLIC_CLIENT_PATH)") < refresh.index("_read_json(SYNCED_PUBLIC_CLIENT_PATH)")
    assert 'synced_public.get("client_id") == baseline_public.get("client_id")' in refresh
    service = STATUS_AGENT_SERVICE.read_text(encoding="utf-8")
    assert "StateDirectory=clientflow/status" in service
    assert "StateDirectoryMode=0711" in service
    assert "ProtectSystem=strict" in service
