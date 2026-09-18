from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import accounts, cli
from clientflow_release.transaction import Layout


def test_detect_bootstrap_user_uses_exact_sudo_user(monkeypatch):
    monkeypatch.setenv("SUDO_USER", "ubuntu-bootstrap")
    monkeypatch.setattr(
        accounts.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_uid=1000) if name == "ubuntu-bootstrap" else (_ for _ in ()).throw(KeyError(name)),
    )
    assert accounts.detect_bootstrap_user() == "ubuntu-bootstrap"


def test_detect_bootstrap_user_protects_clientflow_accounts(monkeypatch):
    monkeypatch.setenv("SUDO_USER", accounts.KIOSK_USER)
    assert accounts.detect_bootstrap_user() is None
    monkeypatch.setenv("SUDO_USER", accounts.ADMIN_USER)
    assert accounts.detect_bootstrap_user() is None


def test_cleanup_bootstrap_user_removes_only_exact_recorded_user(monkeypatch):
    present = {"ubuntu-bootstrap"}
    calls: list[list[str]] = []

    def fake_getpwnam(name: str):
        if name not in present:
            raise KeyError(name)
        return SimpleNamespace(pw_uid=1000)

    def fake_run(command, **_kwargs):
        command = list(command)
        calls.append(command)
        if command[:2] == ["/usr/sbin/userdel", "--remove"]:
            present.discard(command[-1])
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(accounts.pwd, "getpwnam", fake_getpwnam)
    monkeypatch.setattr(accounts.subprocess, "run", fake_run)

    accounts.cleanup_bootstrap_user("ubuntu-bootstrap")

    assert ["/usr/sbin/userdel", "--remove", "ubuntu-bootstrap"] in calls
    assert all("clientflow-kiosk" not in call for call in calls)
    assert all("cfadmin" not in call for call in calls)


def test_cleanup_bootstrap_user_refuses_protected_identity():
    with pytest.raises(accounts.AccountProvisioningError, match="beskyttet"):
        accounts.cleanup_bootstrap_user(accounts.KIOSK_USER)
    with pytest.raises(accounts.AccountProvisioningError, match="beskyttet"):
        accounts.cleanup_bootstrap_user(accounts.ADMIN_USER)


def test_fresh_conflicts_include_existing_canonical_kiosk(monkeypatch, tmp_path: Path):
    def fake_getpwnam(name: str):
        if name == accounts.KIOSK_USER:
            return SimpleNamespace(pw_uid=1000)
        raise KeyError(name)

    monkeypatch.setattr(cli.pwd, "getpwnam", fake_getpwnam)
    monkeypatch.setattr(cli.grp, "getgrnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    # Account probing intentionally only runs for the real root; make this test
    # exercise that branch without touching the host filesystem.
    monkeypatch.setattr(cli.Path, "__eq__", Path.__eq__)
    # _fresh_conflicts uses layout.root == Path('/').  A synthetic layout does
    # not probe host passwd, so verify the canonical account tuple directly via
    # a real-root layout with path redirected to the temp tree.
    class FakeLayout:
        root = Path("/")
        def path(self, absolute: str) -> Path:
            return tmp_path / absolute.lstrip("/")

    conflicts = cli._fresh_conflicts(FakeLayout())
    assert f"user:{accounts.KIOSK_USER}" in conflicts


def test_successful_first_activation_finalizes_install_state_without_rewriting_binding(monkeypatch, tmp_path: Path):
    layout = Layout(tmp_path)
    state_path = layout.path("/var/lib/clientflow/release/install-state.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    binding = {
        "release_id": "clientflow-1.3.19-seq-1220",
        "version": "1.3.19",
        "release_sequence": 1220,
        "bundle_sha256": "a" * 64,
        "bundle_size": 123,
        "release_approval_reference": "approval/ref",
        "release_candidate_sha256": "b" * 64,
        "source_commit": "c" * 40,
    }
    state = {
        "schema_version": cli.INSTALL_STATE_SCHEMA,
        "fresh_install_binding": binding,
        "install_id": "11111111-1111-4111-8111-111111111111",
        "credential_seed_b64": "seed-for-resume-only",
        "backend_url": "https://example.invalid",
        "kiosk_user": accounts.KIOSK_USER,
        "bootstrap_user": "ubuntu-bootstrap",
        "status": "pending_manual_activation",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    state_path.chmod(0o600)

    monkeypatch.setattr(
        cli,
        "status",
        lambda _layout: {
            "active_release_id": binding["release_id"],
            "active_symlink_release_id": binding["release_id"],
        },
    )

    cli._finalize_install_state_after_activation(layout, binding["release_id"])
    final = json.loads(state_path.read_text(encoding="utf-8"))

    assert final["status"] == "activated"
    assert final["activated_release_id"] == binding["release_id"]
    assert final["fresh_install_binding"] == binding
    assert final["bootstrap_user"] is None
    assert "credential_seed_b64" not in final

def test_pending_manual_activation_state_preserves_exact_bootstrap_user():
    binding = {
        "release_id": "clientflow-1.3.18-seq-1219",
        "version": "1.3.18",
        "release_sequence": 1219,
        "bundle_sha256": "a" * 64,
        "bundle_size": 123,
        "release_approval_reference": "approval/ref",
        "release_candidate_sha256": "b" * 64,
        "source_commit": "c" * 40,
    }
    source_state = {
        "bootstrap_user": "ubuntu-bootstrap",
        "credential_seed_b64": "resume-only",
    }

    final = cli._pending_manual_activation_state(
        source_state,
        binding=binding,
        install_id="11111111-1111-4111-8111-111111111111",
        backend_url="https://example.invalid",
        kiosk_user=accounts.KIOSK_USER,
        client_name="Test client",
        locality=None,
        bootstrap_network_connection=None,
    )

    assert final["status"] == "pending_manual_activation"
    assert final["bootstrap_user"] == "ubuntu-bootstrap"
    assert final["fresh_install_binding"] == binding
    assert "credential_seed_b64" not in final



def test_factory_handoff_conflicts_allow_only_canonical_preprovisioned_accounts_and_activation_sudoers(monkeypatch, tmp_path: Path):
    def fake_getpwnam(name: str):
        if name in {accounts.KIOSK_USER, accounts.ADMIN_USER}:
            return SimpleNamespace(pw_uid=1001)
        raise KeyError(name)

    def fake_getgrnam(name: str):
        if name in {accounts.KIOSK_USER, accounts.ADMIN_USER}:
            return SimpleNamespace(gr_gid=1001)
        raise KeyError(name)

    monkeypatch.setattr(cli.pwd, "getpwnam", fake_getpwnam)
    monkeypatch.setattr(cli.grp, "getgrnam", fake_getgrnam)

    class FakeLayout:
        root = Path("/")

        def path(self, absolute: str) -> Path:
            return tmp_path / absolute.lstrip("/")

    sudoers = tmp_path / "etc/sudoers.d"
    sudoers.mkdir(parents=True)
    (sudoers / "clientflow-factory-activation").write_text("factory", encoding="utf-8")

    normal = cli._fresh_conflicts(FakeLayout())
    assert f"user:{accounts.KIOSK_USER}" in normal
    assert f"user:{accounts.ADMIN_USER}" in normal
    assert "sudoers:clientflow-factory-activation" in normal

    factory = cli._fresh_conflicts(FakeLayout(), allow_factory_handoff=True)
    assert f"user:{accounts.KIOSK_USER}" not in factory
    assert f"user:{accounts.ADMIN_USER}" not in factory
    assert "sudoers:clientflow-factory-activation" not in factory


def test_factory_handoff_state_requires_schema2_ready_exact_identity(tmp_path: Path):
    state_path = tmp_path / "factory-state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "client_name": "Holstebro1",
                "operator_user": "viborg1",
                "kiosk_user": accounts.KIOSK_USER,
                "admin_user": accounts.ADMIN_USER,
                "handoff_ready": True,
            }
        ),
        encoding="utf-8",
    )
    state_path.chmod(0o600)
    layout = Layout(tmp_path / "synthetic-root")
    state = cli._factory_handoff_state(state_path, client_name="Holstebro1", layout=layout)
    assert state is not None
    assert state["operator_user"] == "viborg1"

    state["handoff_ready"] = False
    state_path.write_text(json.dumps(state), encoding="utf-8")
    state_path.chmod(0o600)
    with pytest.raises(RuntimeError, match="ikke valideret"):
        cli._factory_handoff_state(state_path, client_name="Holstebro1", layout=layout)
