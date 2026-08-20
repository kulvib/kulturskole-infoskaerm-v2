from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = REPO_ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release.builder import _create_payload, _create_updater_pyz  # noqa: E402
from clientflow_release.update_auth import generate_update_key  # noqa: E402
from clientflow_release.updater_config import UpdaterConfig  # noqa: E402
from clientflow_release.transaction import (  # noqa: E402
    Layout,
    install_stable_updater_host,
    load_state,
    save_state,
)
from clientflow_release.wipe import wipe  # noqa: E402


def test_51e_updater_pyz_is_deterministic_minimal_and_bootable():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        first = tmp / "first.pyz"
        second = tmp / "second.pyz"
        epoch = 1_700_000_000
        _create_updater_pyz(REPO_ROOT, first, epoch=epoch)
        _create_updater_pyz(REPO_ROOT, second, epoch=epoch)

        assert first.read_bytes() == second.read_bytes()
        assert first.read_bytes().startswith(b"#!/usr/bin/env python3\n")
        assert os.stat(first).st_mode & 0o111

        with zipfile.ZipFile(first) as archive:
            names = set(archive.namelist())
        assert "__main__.py" in names
        assert "clientflow_release/updater_entrypoint.py" in names
        assert "clientflow_release/updater_client.py" in names
        assert "clientflow_release/updater_transport.py" in names
        assert "clientflow_release_format/bundle.py" in names
        assert "clientflow_release/transaction.py" not in names
        assert "clientflow_release/cli.py" not in names

        credentials = tmp / "credentials"
        credentials.mkdir()
        result = subprocess.run(
            [sys.executable, str(first)],
            env={
                **os.environ,
                "CREDENTIALS_DIRECTORY": str(credentials),
                "STATE_DIRECTORY": str(tmp / "state"),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        assert result.returncode == 1
        assert "clientflow-updater:" in result.stderr
        assert "ModuleNotFoundError" not in result.stderr


def test_51e_verified_release_payload_contains_the_exact_updater_pyz():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        updater = tmp / "clientflow-updater.pyz"
        payload = tmp / "payload.tar"
        _create_updater_pyz(REPO_ROOT, updater, epoch=1_700_000_000)
        expected = updater.read_bytes()

        _complete, _runtime_files = _create_payload(
            REPO_ROOT,
            payload,
            version="1.2.0",
            epoch=1_700_000_000,
            runtime_inputs=None,
            updater_pyz=updater,
        )

        with tarfile.open(payload, "r:") as archive:
            member = archive.getmember("clientflow-1.2.0/release/updater/clientflow-updater.pyz")
            extracted = archive.extractfile(member)
            assert extracted is not None
            actual = extracted.read()
        assert actual == expected
        assert member.mode == 0o755


def test_51e_stable_host_materializes_exact_verified_bytes_outside_active_release():
    with tempfile.TemporaryDirectory() as raw_tmp:
        root = Path(raw_tmp)
        layout = Layout(root)
        release_id = "clientflow-1.2.0-seq-1200"
        release_root = layout.releases / release_id
        source = release_root / "release/updater/clientflow-updater.pyz"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"#!/usr/bin/env python3\nstable-updater\n")
        source.chmod(0o555)

        state = load_state(layout)
        state["installed"][release_id] = {"release_sequence": 1200}
        save_state(layout, state)

        result = install_stable_updater_host(release_id, layout=layout)
        installed = layout.stable_updater_pyz
        assert result["status"] == "stable_updater_host_installed"
        assert installed == root / "usr/lib/clientflow/updater/clientflow-updater.pyz"
        assert installed.read_bytes() == source.read_bytes()
        assert os.stat(installed).st_mode & 0o777 == 0o555
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == result["updater_sha256"]
        assert not (layout.active.exists() or layout.active.is_symlink())

        persisted = load_state(layout)
        assert persisted["history"][-1]["event"] == "stable_updater_host_installed"


def test_51e_systemd_credential_ca_override_avoids_root_only_master_path(monkeypatch):
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        credentials = tmp / "credentials"
        credentials.mkdir()
        private_key = credentials / "update-private-key.pem"
        _public, key_id, _jwk, _jkt = generate_update_key(private_key)
        credential_id = "11111111-1111-4111-8111-111111111111"
        credential = credentials / "update-credential.json"
        credential.write_text(
            "{\n"
            '  "schema_version": 1,\n'
            '  "backend_url": "https://display.example.invalid",\n'
            '  "client_id": 23,\n'
            f'  "credential_id": "{credential_id}",\n'
            f'  "key_id": "{key_id}",\n'
            '  "algorithm": "Ed25519",\n'
            '  "token_audience": "urn:planiq:clientflow-update:token",\n'
            '  "access_token_issuer": "https://display.example.invalid",\n'
            '  "access_token_audience": "urn:planiq:clientflow-update:resource",\n'
            '  "tls_ca_file": "/etc/clientflow/tls/ca.pem"\n'
            "}\n",
            encoding="utf-8",
        )
        credential.chmod(0o600)
        ca_copy = credentials / "update-ca.pem"
        ca_copy.write_text("test-ca-copy\n", encoding="utf-8")
        ca_copy.chmod(0o600)

        monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
        monkeypatch.setenv("CLIENTFLOW_UPDATE_CA_FILE", str(ca_copy))
        monkeypatch.setenv("STATE_DIRECTORY", str(tmp / "state"))
        config = UpdaterConfig.from_environment()
        assert config.ca_file == ca_copy
        assert config.ca_file != Path("/etc/clientflow/tls/ca.pem")


def test_51e_wipe_removes_timer_definition_and_stable_support_tree_in_fake_root():
    with tempfile.TemporaryDirectory() as raw_tmp:
        root = Path(raw_tmp)
        layout = Layout(root)
        layout.unit_root.mkdir(parents=True)
        (layout.unit_root / "clientflow-updater.timer").write_text("[Timer]\nOnActiveSec=1min\n", encoding="utf-8")
        layout.sysusers_file.parent.mkdir(parents=True, exist_ok=True)
        layout.sysusers_file.write_text("g clientflow-updater -\n", encoding="utf-8")
        layout.tmpfiles_file.parent.mkdir(parents=True, exist_ok=True)
        layout.tmpfiles_file.write_text("d /var/lib/clientflow 0755 root root -\n", encoding="utf-8")
        layout.stable_updater_root.mkdir(parents=True)
        layout.stable_updater_pyz.write_bytes(b"stable")
        (layout.path("/var/lib/clientflow/updater")).mkdir(parents=True)

        wipe(
            reason="51E deterministic cleanup test",
            confirm="DESTROY-CLIENTFLOW-STATE",
            layout=layout,
        )

        assert not (layout.unit_root / "clientflow-updater.timer").exists()
        assert not layout.sysusers_file.exists()
        assert not layout.tmpfiles_file.exists()
        assert not layout.stable_support_root.exists()
        assert not layout.path("/var/lib/clientflow").exists()
