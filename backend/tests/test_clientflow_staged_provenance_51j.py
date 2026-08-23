from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from clientflow_release import transaction  # noqa: E402
from clientflow_release.transaction import Layout, TransactionError  # noqa: E402


RELEASE_ID = "clientflow-1.3.0-seq-1201"
BUNDLE_SHA = "b" * 64
CANDIDATE_SHA = "c" * 64
SOURCE_COMMIT = "d" * 40
APPROVAL = "release-51j-approved"


def _manifest() -> dict:
    return {
        "release_id": RELEASE_ID,
        "version": "1.3.0",
        "release_sequence": 1201,
        "release_approval": {
            "reference": APPROVAL,
            "candidate_sha256": CANDIDATE_SHA,
        },
        "source": {"commit": SOURCE_COMMIT, "dirty": False},
        "payload": {"root": "clientflow-1.3.0"},
        "activation": {"health_timeout_seconds": 120},
    }


def _stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Layout:
    layout = Layout(tmp_path / "root")
    bundle = tmp_path / "approved.tar"
    bundle.write_bytes(b"approved-bundle-A")
    manifest = _manifest()

    class FakePayload:
        def assert_unchanged(self):
            return None

    payload = FakePayload()
    calls = []

    def fake_open_verified_bundle(path, *, require_deployable, required_install_mode):
        calls.append((path, require_deployable, required_install_mode))
        handle = bundle.open("rb")
        # Simulate a hostile pathname replacement after the exact file identity
        # has been opened and verified. stage_bundle must never reopen this path.
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"bundle-B")
        replacement.replace(bundle)
        return manifest, payload, 1234, BUNDLE_SHA, handle

    def fake_extract(_payload, destination, *, expected_root):
        assert _payload == payload
        root = destination / expected_root
        root.mkdir(parents=True)
        (root / "marker.txt").write_text("payload-A", encoding="utf-8")
        return root

    monkeypatch.setattr(transaction, "open_verified_bundle", fake_open_verified_bundle)
    monkeypatch.setattr(transaction, "extract_verified_payload", fake_extract)
    monkeypatch.setattr(transaction, "_validate_release_tree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "prepare_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "_validate_prepared_release_tree", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "_make_immutable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction, "_seal_published_release", lambda *_args, **_kwargs: None)

    result = transaction.stage_bundle(
        bundle,
        release_id=RELEASE_ID,
        expected_bundle_sha256=BUNDLE_SHA,
        layout=layout,
    )
    assert result["status"] == "staged"
    assert len(calls) == 1
    return layout


def test_51j_staging_persists_exact_artifact_provenance_and_uses_state_schema_2(tmp_path, monkeypatch):
    layout = _stage(tmp_path, monkeypatch)
    state = json.loads(layout.state_file.read_text(encoding="utf-8"))
    assert state["schema_version"] == 2
    record = state["installed"][RELEASE_ID]
    assert record["bundle_sha256"] == BUNDLE_SHA
    assert record["bundle_size"] == 1234
    assert record["release_approval_reference"] == APPROVAL
    assert record["release_candidate_sha256"] == CANDIDATE_SHA
    assert record["source_commit"] == SOURCE_COMMIT
    assert state["history"][-1]["bundle_sha256"] == BUNDLE_SHA
    assert state["history"][-1]["release_approval_reference"] == APPROVAL


def test_51j_activation_rejects_free_text_approval_and_uses_artifact_approval(tmp_path, monkeypatch):
    layout = _stage(tmp_path, monkeypatch)
    seen = []

    def fake_activate(_layout, _state, release_id, approval):
        seen.append((release_id, approval))
        return {"status": "active", "release_id": release_id}

    monkeypatch.setattr(transaction, "_activate_release", fake_activate)

    with pytest.raises(TransactionError, match="immutable release-approval"):
        transaction.activate_release(
            RELEASE_ID,
            expected_release_approval_reference="some-other-change",
            layout=layout,
        )
    assert seen == []

    result = transaction.activate_release(
        RELEASE_ID,
        expected_release_approval_reference=APPROVAL,
        layout=layout,
    )
    assert result["status"] == "active"
    assert seen == [(RELEASE_ID, APPROVAL)]


def test_51j_activation_fails_closed_if_staged_provenance_is_modified(tmp_path, monkeypatch):
    layout = _stage(tmp_path, monkeypatch)
    state = json.loads(layout.state_file.read_text(encoding="utf-8"))
    state["installed"][RELEASE_ID]["source_commit"] = "e" * 40
    layout.state_file.write_text(json.dumps(state), encoding="utf-8")
    layout.state_file.chmod(0o600)

    monkeypatch.setattr(
        transaction,
        "_activate_release",
        lambda *_args, **_kwargs: pytest.fail("activation må ikke nås"),
    )
    with pytest.raises(TransactionError, match="inkonsistent provenance"):
        transaction.activate_release(
            RELEASE_ID,
            expected_release_approval_reference=APPROVAL,
            layout=layout,
        )


def test_51j_stage_source_has_no_hash_then_reopen_bundle_contract():
    source = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text(encoding="utf-8")
    stage = source.split("def stage_bundle(", 1)[1].split("\ndef _atomic_copy", 1)[0]
    assert "open_verified_bundle(" in stage
    assert "verify_bundle(" not in stage
    assert "sha256_file(bundle" not in stage
    provenance_source = source.split("def _manifest_provenance(", 1)[1].split("\ndef _assert_record_provenance", 1)[0]
    for field in (
        "bundle_sha256",
        "bundle_size",
        "release_approval_reference",
        "release_candidate_sha256",
        "source_commit",
    ):
        assert field in provenance_source or field in stage


def test_51j_activation_and_rollback_cli_use_expected_artifact_approval_semantics():
    cli = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    transaction_source = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text(encoding="utf-8")
    assert cli.count('add_argument("--expected-release-approval-reference", required=True)') == 4
    assert 'activate.add_argument("--approval-reference"' not in cli
    assert 'rollback.add_argument("--approval-reference"' not in cli
    rollback_source = transaction_source.split("def rollback_release(", 1)[1].split("\ndef status", 1)[0]
    assert "_canonical_activation_approval(" in rollback_source
    assert "expected_release_approval_reference" in rollback_source
    assert 'installed[release_id]["approval_reference"]' not in transaction_source
