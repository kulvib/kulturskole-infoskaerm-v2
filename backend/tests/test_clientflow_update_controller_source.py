from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_controller_updater_remains_unprivileged_and_triggers_separate_root_controller():
    updater = read("client/systemd/clientflow-updater.service")
    controller = read("client/systemd/clientflow-update-controller.service")

    assert "User=clientflow-updater" in updater
    assert "CapabilityBoundingSet=\n" in updater
    assert "ExecStart=/usr/bin/python3 -I /usr/lib/clientflow/updater/clientflow-updater.pyz" in updater
    assert "OnSuccess=clientflow-update-controller.service" in updater
    assert "/opt/clientflow/active" not in updater

    assert "User=root" in controller
    assert "ExecStart=/bin/sh /opt/clientflow/active/client-runtime/libexec/update-controller" in controller
    assert "Environment=CLIENTFLOW_UPDATE_SOURCE_STATE_DIR=/var/lib/clientflow/updater" in controller
    assert "StateDirectory=clientflow/update-controller" in controller
    assert "LoadCredential=update-credential.json:/etc/clientflow/update/credential.json" in controller
    assert "LoadCredential=update-private-key.pem:/etc/clientflow/update/private-key.pem" in controller
    assert "clientflow.target" not in controller

    wipe = read("client/release/lib/clientflow_release/wipe.py")
    controller_stop = wipe.index('"stop", "clientflow-update-controller.service"')
    remove_definitions = wipe.index("_remove_definitions(layout)")
    assert controller_stop < remove_definitions


def test_controller_pins_active_release_and_uses_isolated_runtime():
    helper = read("client/libexec/update-controller")
    assert "/usr/bin/readlink -f /opt/clientflow/active" in helper
    assert 'ACTIVE_ROOT="$(' in helper
    assert 'ACTIVE_PARENT="${ACTIVE_ROOT%/*}"' in helper
    assert '[ "$ACTIVE_PARENT" != "/opt/clientflow/releases" ]' in helper
    assert 'RUNTIME_PYTHON="$ACTIVE_ROOT/runtime/bin/python"' in helper
    assert 'RELEASE_LIB="$ACTIVE_ROOT/release/lib"' in helper
    assert 'exec "$RUNTIME_PYTHON" -I -c' in helper
    assert "clientflow_release.update_controller_entrypoint" in helper


def test_controller_secure_handoff_is_no_follow_hash_bound_and_root_private():
    controller = read("client/release/lib/clientflow_release/update_controller.py")
    assert "os.O_NOFOLLOW" in controller
    assert "os.fstat(source_fd)" in controller
    assert "_identity(before) != _identity(after)" in controller
    assert "snapshot.bundle_size" in controller
    assert "snapshot.bundle_sha256" in controller
    assert "os.fchmod(temporary_fd, 0o600)" in controller
    assert "os.replace(temporary, destination)" in controller
    assert "Root-owned handoff kunne ikke genverificeres" in controller
    assert "er ikke root-owned" in controller
    assert "fcntl.flock" in controller
    assert "controller.lock" in controller
    assert "cleanup_handoffs" in controller
    assert "stage_bundle" in controller
    assert "system_agent" not in controller
    assert "system_broker" not in controller
    assert '"latest"' not in controller
    assert "client-runtime/systemd/clientflow-update-controller.service" in controller
    assert "client-runtime/libexec/update-controller" in controller
    assert "release/lib/clientflow_release/update_controller.py" in controller


def test_controller_orders_stage_backend_gate_then_local_activation():
    controller = read("client/release/lib/clientflow_release/update_controller.py")
    stage_section = controller[controller.index("def _stage_verified"):controller.index("def _report_staged")]
    report_section = controller[controller.index("def _report_staged"):controller.index("def _authorize_activation")]
    authorize_section = controller[controller.index("def _authorize_activation"):controller.index("def _report_success")]
    activation_section = controller[controller.index("def _activate_or_reconcile"):controller.index("def run_once")]

    assert "self.stage_func(" in stage_section
    assert 'event_type="staged"' in report_section
    assert "self.transport.start_activation(" in authorize_section
    assert "self.activate_func(" in activation_section
    assert "expected_release_approval_reference=snapshot.release_approval_reference" in activation_section
