from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_51e_service_is_stable_unprivileged_and_credential_bound():
    service = read("client/systemd/clientflow-updater.service")
    timer = read("client/systemd/clientflow-updater.timer")
    sysusers = read("client/sysusers.d/clientflow.conf")

    assert "User=clientflow-updater" in service
    assert "Group=clientflow-updater" in service
    assert "ExecStart=/usr/bin/python3 -I /usr/lib/clientflow/updater/clientflow-updater.pyz" in service
    assert "LoadCredential=update-credential.json:/etc/clientflow/update/credential.json" in service
    assert "LoadCredential=update-private-key.pem:/etc/clientflow/update/private-key.pem" in service
    assert "LoadCredential=update-ca.pem:/etc/clientflow/update/tls-ca.pem" in service
    assert "Environment=CLIENTFLOW_UPDATE_CA_FILE=%d/update-ca.pem" in service
    assert "StateDirectory=clientflow/updater" in service
    assert "StateDirectoryMode=0700" in service
    assert "ProtectSystem=strict" in service
    assert "NoNewPrivileges=yes" in service
    assert "CapabilityBoundingSet=\n" in service
    assert "/opt/clientflow/active" not in service
    assert "clientflow.target" not in service

    assert "OnActiveSec=" in timer
    assert "OnUnitActiveSec=" in timer
    assert "Unit=clientflow-updater.service" in timer
    assert "WantedBy=timers.target" in timer
    assert "clientflow.target" not in timer
    assert "clientflow-updater" in sysusers
    assert "/var/lib/clientflow/updater" in sysusers


def test_51e_installer_wires_updater_only_after_enrollment_and_keeps_target_inactive():
    cli = read("client/release/lib/clientflow_release/cli.py")
    transaction = read("client/release/lib/clientflow_release/transaction.py")

    complete_index = cli.index("complete(\n")
    updater_index = cli.index("install_stable_updater_host(release_id, layout=layout)", complete_index)
    final_index = cli.index('"status": "pending_manual_activation"', updater_index)
    assert complete_index < updater_index < final_index

    assert '"clientflow*.timer"' in transaction
    assert '".timer"' in transaction
    assert '"/usr/lib/clientflow"' in cli
    assert '"clientflow-updater"' in cli
    assert '["/usr/bin/systemctl", "enable", "--now", "clientflow-updater.timer"]' in transaction
    assert '_quiesce_runtime(layout)' in transaction
    assert '["/usr/bin/systemctl", "disable", "clientflow.target"]' in transaction


def test_51e_wipe_removes_stable_plane_without_reusing_legacy_activation():
    wipe = read("client/release/lib/clientflow_release/wipe.py")
    updater_entrypoint = read("client/release/lib/clientflow_release/updater_entrypoint.py")
    combined = wipe + updater_entrypoint

    assert '"clientflow-updater"' in wipe
    assert '"/usr/lib/clientflow"' in wipe
    assert '"disable", "--now", "clientflow-updater.timer"' in wipe
    assert '"stop", "clientflow-updater.service"' in wipe
    assert "_quiesce_runtime(layout, require_target=False)" in wipe
    assert "StableUpdaterClient" in updater_entrypoint
    assert "stage_bundle" not in updater_entrypoint
    assert "activate_release" not in updater_entrypoint
    assert "system_agent" not in combined
    assert "system_broker" not in combined
