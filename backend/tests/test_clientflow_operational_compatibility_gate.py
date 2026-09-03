from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import cli as installer_cli  # noqa: E402
from clientflow_release import runtime_prepare, transaction  # noqa: E402
from clientflow_release.transaction import Layout, TransactionError  # noqa: E402


RELEASE_ID = "clientflow-1.3.10-seq-1211"
APPROVAL = "clientflow-1.3.10-seq-1211/test-approval"


def _activation_state(layout: Layout) -> None:
    release_root = layout.releases / RELEASE_ID
    release_root.mkdir(parents=True)
    manifest = {
        "release_id": RELEASE_ID,
        "version": "1.3.10",
        "release_sequence": 1211,
        "release_approval": {"reference": APPROVAL, "candidate_sha256": "c" * 64},
        "source": {"commit": "d" * 40, "dirty": False},
        "activation": {"health_timeout_seconds": 120},
    }
    (release_root / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    state = {
        "schema_version": transaction.STATE_SCHEMA,
        "installed": {
            RELEASE_ID: {
                "manifest_sha256": transaction._manifest_digest(manifest),
                "bundle_sha256": "b" * 64,
                "bundle_size": 1234,
                "release_approval_reference": APPROVAL,
                "release_candidate_sha256": "c" * 64,
                "source_commit": "d" * 40,
            }
        },
        "active_release_id": None,
        "previous_release_id": None,
        "staged_release_id": RELEASE_ID,
        "history": [],
    }
    transaction.save_state(layout, state)


def test_first_activation_requires_backend_approval_proof_before_local_activation(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "root")
    _activation_state(layout)
    monkeypatch.setattr(
        transaction,
        "_activate_release",
        lambda *_args, **_kwargs: pytest.fail("local activation must not start without backend approval proof"),
    )
    monkeypatch.setattr(
        transaction,
        "_enable_stable_updater_timer",
        lambda *_args, **_kwargs: pytest.fail("updater timer must not start before backend approval proof"),
    )

    with pytest.raises(TransactionError, match="backend-approved"):
        transaction.activate_release(
            RELEASE_ID,
            expected_release_approval_reference=APPROVAL,
            layout=layout,
        )


def test_first_activation_runs_proof_before_mutation(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "root")
    _activation_state(layout)
    calls: list[str] = []

    def proof(_layout: Layout) -> None:
        calls.append("proof")

    def activate(_layout, _state, _release_id, _approval, **_kwargs):
        calls.append("activate")
        return {"status": "active", "release_id": RELEASE_ID}

    monkeypatch.setattr(transaction, "_activate_release", activate)
    result = transaction.activate_release(
        RELEASE_ID,
        expected_release_approval_reference=APPROVAL,
        layout=layout,
        first_activation_authorizer=proof,
    )
    assert result["status"] == "active"
    assert calls == ["proof", "activate"]


def test_first_activation_crash_resume_reproves_backend_approval_with_target_symlink(
    tmp_path,
    monkeypatch,
):
    layout = Layout(tmp_path / "root")
    _activation_state(layout)
    state = transaction.load_state(layout)
    state["activation_intent"] = {
        "release_id": RELEASE_ID,
        "previous_release_id": None,
        "release_approval_reference": APPROVAL,
        "started_at": "2026-09-03T18:00:00Z",
    }
    transaction.save_state(layout, state)
    transaction.atomic_symlink(f"releases/{RELEASE_ID}", layout.active)

    monkeypatch.setattr(
        transaction,
        "_activate_release",
        lambda *_args, **_kwargs: pytest.fail(
            "crash-resume must not continue before backend approval is re-proven"
        ),
    )

    with pytest.raises(TransactionError, match="backend-approved"):
        transaction.activate_release(
            RELEASE_ID,
            expected_release_approval_reference=APPROVAL,
            layout=layout,
        )

    calls: list[str] = []

    def proof(_layout: Layout) -> None:
        calls.append("proof")

    def activate(_layout, _state, _release_id, _approval, **_kwargs):
        calls.append("activate")
        return {"status": "active", "release_id": RELEASE_ID}

    monkeypatch.setattr(transaction, "_activate_release", activate)
    result = transaction.activate_release(
        RELEASE_ID,
        expected_release_approval_reference=APPROVAL,
        layout=layout,
        first_activation_authorizer=proof,
    )
    assert result["status"] == "active"
    assert calls == ["proof", "activate"]


def test_durably_active_release_skips_fresh_first_activation_gate(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "root")
    _activation_state(layout)
    state = transaction.load_state(layout)
    state["active_release_id"] = RELEASE_ID
    state["staged_release_id"] = None
    state["installed"][RELEASE_ID]["activated_at"] = "2026-09-03T18:01:00Z"
    transaction.save_state(layout, state)
    transaction.atomic_symlink(f"releases/{RELEASE_ID}", layout.active)

    result = transaction.activate_release(
        RELEASE_ID,
        expected_release_approval_reference=APPROVAL,
        layout=layout,
    )
    assert result == {"status": "already_active", "release_id": RELEASE_ID}


def test_pending_updater_timer_requires_exact_disabled_inactive(monkeypatch):
    states = {
        "is-enabled": ("disabled\n", 1),
        "is-active": ("inactive\n", 3),
    }

    def fake_run(command, **_kwargs):
        action = command[1]
        stdout, returncode = states[action]
        return installer_cli.subprocess.CompletedProcess(
            command,
            returncode,
            stdout=stdout,
        )

    monkeypatch.setattr(installer_cli.subprocess, "run", fake_run)

    installer_cli._validate_pending_updater_timer_state()

    states["is-enabled"] = ("enabled\n", 0)
    with pytest.raises(RuntimeError, match="disabled og inactive"):
        installer_cli._validate_pending_updater_timer_state()

    states["is-enabled"] = ("disabled\n", 1)
    states["is-active"] = ("failed\n", 3)
    with pytest.raises(RuntimeError, match="disabled og inactive"):
        installer_cli._validate_pending_updater_timer_state()


def test_systemd_runtime_entrypoints_are_all_in_relocation_inventory(tmp_path):
    systemd = ROOT / "client/systemd"
    expected: set[str] = set()
    prefix = "/opt/clientflow/active/runtime/bin/"
    for unit in systemd.glob("*.service"):
        for line in unit.read_text(encoding="utf-8").splitlines():
            if line.startswith("ExecStart=" + prefix):
                expected.add(line.split(prefix, 1)[1].split()[0])
    assert expected
    assert expected <= set(runtime_prepare.CLIENTFLOW_ENTRYPOINTS)
    assert "clientflow-calendar" in expected

    runtime = tmp_path / "runtime"
    (runtime / "bin").mkdir(parents=True)
    for name in runtime_prepare.CLIENTFLOW_ENTRYPOINTS:
        path = runtime / "bin" / name
        path.write_text("#!/tmp/stage/runtime/bin/python\nprint('ok')\n", encoding="utf-8")
        path.chmod(0o755)
    runtime_prepare._rewrite_clientflow_entrypoints(runtime)
    for name in expected:
        first = (runtime / "bin" / name).read_text(encoding="utf-8").splitlines()[0]
        assert first == f"#!{runtime_prepare.ACTIVE_RUNTIME_PYTHON}"


def test_fresh_remote_desktop_configuration_is_generic_and_bound_to_kiosk_user(tmp_path):
    layout = Layout(tmp_path / "root")
    release_config = layout.releases / RELEASE_ID / "client-runtime/config-examples"
    release_config.mkdir(parents=True)
    (release_config / "livestream.json").write_text('{"schema_version":1}\n', encoding="utf-8")
    (release_config / "remote-desktop.json").write_text(
        (ROOT / "client/config-examples/remote-desktop.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for path in release_config.iterdir():
        path.chmod(0o644)

    installer_cli._copy_install_configuration(
        layout,
        RELEASE_ID,
        ca_file=None,
        kiosk_user="kiosk-a",
    )
    config = json.loads(layout.path("/etc/clientflow/remote-desktop.json").read_text(encoding="utf-8"))
    assert config == {
        "schema_version": 1,
        "capture_backend": "mutter-pipewire",
        "kiosk_user": "kiosk-a",
    }
    serialized = json.dumps(config)
    for forbidden in ("/run/user/1000", "xauthority", "ffmpeg-x11", '"display"'):
        assert forbidden not in serialized.lower()


def test_status_credential_is_used_as_exact_backend_approval_proof(tmp_path, monkeypatch):
    layout = Layout(tmp_path / "root")
    credential_path = layout.path("/etc/clientflow/credentials/status.json")
    credential_path.parent.mkdir(parents=True)
    credential_id = "11111111-2222-4333-8444-555555555555"
    credential = {
        "schema_version": 1,
        "backend_url": "https://backend.example.invalid",
        "client_id": 42,
        "domain": "status",
        "credential_id": credential_id,
        "client_secret": "cf_status_" + "x" * 48,
        "token_issuer": "clientflow-domain-auth",
    }
    credential_path.write_text(json.dumps(credential), encoding="utf-8")
    credential_path.chmod(0o600)
    seen = {}

    def fake_proof(**kwargs):
        seen.update(kwargs)
        return {"access_token": "approved"}

    monkeypatch.setattr(installer_cli, "prove_client_approval", fake_proof)
    installer_cli._prove_backend_client_approved(layout)
    assert seen == {
        "backend_url": credential["backend_url"],
        "client_id": 42,
        "credential_id": credential_id,
        "client_secret": credential["client_secret"],
        "token_issuer": credential["token_issuer"],
        "ca_file": None,
    }


def test_backend_approval_proof_rejects_malformed_status_token_response(monkeypatch):
    from clientflow_release import enrollment

    credential_id = "11111111-2222-4333-8444-555555555555"
    valid = {
        "access_token": "signed-token",
        "token_type": "bearer",
        "client_id": 42,
        "credential_id": credential_id,
        "domain": "status",
        "audience": "clientflow-domain:status",
        "issuer": "clientflow-domain-auth",
    }
    monkeypatch.setattr(enrollment, "_post_json", lambda *_args, **_kwargs: dict(valid))
    result = enrollment.prove_client_approval(
        backend_url="https://backend.example.invalid",
        client_id=42,
        credential_id=credential_id,
        client_secret="cf_status_" + "x" * 48,
        token_issuer="clientflow-domain-auth",
        ca_file=None,
    )
    assert result["access_token"] == "signed-token"

    malformed = dict(valid)
    malformed["client_id"] = 43
    monkeypatch.setattr(enrollment, "_post_json", lambda *_args, **_kwargs: malformed)
    with pytest.raises(enrollment.EnrollmentError, match="ugyldig status-token-kontrakt"):
        enrollment.prove_client_approval(
            backend_url="https://backend.example.invalid",
            client_id=42,
            credential_id=credential_id,
            client_secret="cf_status_" + "x" * 48,
            token_issuer="clientflow-domain-auth",
            ca_file=None,
        )
