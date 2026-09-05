from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import cli
from clientflow_release.transaction import Layout


def test_public_client_metadata_is_non_secret_and_kiosk_readable(tmp_path: Path) -> None:
    layout = Layout(tmp_path)
    path = layout.path("/var/lib/clientflow/client-public.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    cli._write_public_client_metadata(
        layout,
        client_id=42,
        client_name="Viborg – foyer",
        locality="Kulturskolen",
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {
        "schema_version": cli.PUBLIC_CLIENT_METADATA_SCHEMA,
        "client_id": 42,
        "name": "Viborg – foyer",
        "locality": "Kulturskolen",
        "kiosk_user": "clientflow-kiosk",
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    serialized = path.read_text(encoding="utf-8").lower()
    for forbidden in ("secret", "credential", "private_key", "resume", "bundle_sha256"):
        assert forbidden not in serialized


def test_local_gui_preserves_legacy119_sections_copy_and_safe_actions() -> None:
    path = ROOT / "client/libexec/local-gui"
    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")

    for section in (
        '"Handlinger"',
        '"Systeminfo"',
        '"Kioskinfo"',
        '"Netværksinfo"',
        '"Kalender – næste 7 dage"',
    ):
        assert section in source

    for field in (
        '"Navn / Lokation"',
        '"Backend-status"',
        '"Kiosk URL"',
        '"Aktiv forbindelse"',
        '"Aktiv IP"',
        '"Aktiv MAC"',
        '"WiFi IP"',
        '"WiFi MAC"',
        '"LAN IP"',
        '"LAN MAC"',
    ):
        assert field in source

    assert 'PUBLIC_CLIENT_PATH' in source
    assert 'display.get_clipboard().set_text(value)' in source
    assert '"Kopieret!"' in source
    assert '"Start kiosk"' in source
    assert '"Stop kiosk"' in source
    assert '"Skift til administrator"' in source
    assert 'SWITCH_USER_HELPER' in source

    # The local GUI keeps the frozen domains read-only and only mutates Display
    # through the existing narrow RPC.
    assert '_service_state("clientflow-livestream-producer.service")' in source
    assert '_service_state("clientflow-remote-desktop-agent.service")' in source
    assert '_service_state("clientflow-terminal-agent.service")' in source
    assert '"action": action' in source


def test_switch_user_helper_only_locks_the_exact_active_kiosk_session() -> None:
    path = ROOT / "client/libexec/clientflow-switch-user-admin"
    source = path.read_text(encoding="utf-8")
    subprocess.run(["/usr/bin/bash", "-n", str(path)], check=True)

    assert 'EXPECTED_USER="${CLIENTFLOW_KIOSK_USER:-clientflow-kiosk}"' in source
    assert 'show-seat seat0 -p ActiveSession --value' in source
    for check in ('"$NAME" != "$EXPECTED_USER"', '"$SEAT" != "seat0"', '"$REMOTE" != "no"', '"$CLASS" != "user"', '"$ACTIVE" != "yes"'):
        assert check in source
    assert 'exec /usr/bin/loginctl lock-session "$SESSION_ID"' in source
    assert "systemctl" not in source
    assert "sudo" not in source


def test_recovery_status_and_bundle_are_executable_and_secret_free(tmp_path: Path) -> None:
    path = ROOT / "client/libexec/clientflow-recovery"
    source = path.read_text(encoding="utf-8")
    subprocess.run(["/usr/bin/bash", "-n", str(path)], check=True)

    status = subprocess.run(
        ["/usr/bin/bash", str(path), "status"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )
    assert status.returncode == 0
    assert "ClientFlow local recovery status" in status.stdout

    env = {**os.environ, "CLIENTFLOW_SUPPORT_OUTPUT_DIR": str(tmp_path)}
    bundle = subprocess.run(
        ["/usr/bin/bash", str(path), "bundle"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )
    assert bundle.returncode == 0, bundle.stdout
    archives = list(tmp_path.glob("clientflow-support-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        names = archive.getnames()
    assert any(name.endswith("/status.txt") for name in names)
    assert all("/etc/clientflow" not in name for name in names)
    assert all("credential" not in name.lower() for name in names)
    assert all("private" not in name.lower() for name in names)

    # Mutation is bounded to the canonical aggregate target; frozen units are
    # mentioned only in read-only status collection.
    restart = source[source.index("restart_target()"):source.index('case "$CMD"')]
    assert 'TARGET="clientflow.target"' in source
    assert '/usr/bin/systemctl restart "$TARGET"' in restart
    assert "clientflow-livestream" not in restart
    assert "clientflow-remote-desktop" not in restart
    assert "clientflow-terminal" not in restart
