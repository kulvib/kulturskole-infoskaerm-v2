from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
import uuid

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from service1.clientflow_fresh_install_auth import issue_fresh_install_authorization  # noqa: E402
from service1.routers import enrollment as enrollment_router  # noqa: E402


BINDING = {
    "release_id": "clientflow-1.3.3-seq-1204",
    "version": "1.3.3",
    "release_sequence": 1204,
    "bundle_sha256": "a" * 64,
    "bundle_size": 80123456,
    "release_approval_reference": "clientflow-1.3.3-seq-1204/test-approval",
    "release_candidate_sha256": "b" * 64,
    "source_commit": "c" * 40,
}


def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64",
        base64.urlsafe_b64encode(b"k" * 32).decode("ascii"),
    )


def _authorization(monkeypatch: pytest.MonkeyPatch, *, token_id: int, expires_at: datetime) -> str:
    _set_key(monkeypatch)
    return issue_fresh_install_authorization(
        enrollment_token_id=token_id,
        expires_at=expires_at,
        snapshot={
            "target_release_id": BINDING["release_id"],
            "target_version": BINDING["version"],
            "target_release_sequence": BINDING["release_sequence"],
            "bundle_sha256": BINDING["bundle_sha256"],
            "bundle_size": BINDING["bundle_size"],
            "release_approval_reference": BINDING["release_approval_reference"],
            "release_candidate_sha256": BINDING["release_candidate_sha256"],
            "source_commit": BINDING["source_commit"],
        },
    )


def test_initial_claim_authorization_accepts_only_same_token_and_exact_release_binding(monkeypatch):
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    raw = _authorization(monkeypatch, token_id=42, expires_at=expires_at)
    token = SimpleNamespace(id=42, expires_at=expires_at.replace(tzinfo=None))

    authorization = enrollment_router._verify_initial_fresh_install_authorization(
        token=token,
        authorization_value=raw,
        binding=dict(BINDING),
    )
    assert authorization.release_id == BINDING["release_id"]
    assert authorization.bundle_sha256 == BINDING["bundle_sha256"]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("release_id", "clientflow-1.3.4-seq-1204"),
        ("version", "1.3.4"),
        ("release_sequence", 1205),
        ("bundle_sha256", "d" * 64),
        ("bundle_size", 80123457),
        ("release_approval_reference", "different-approval"),
        ("release_candidate_sha256", "e" * 64),
        ("source_commit", "f" * 40),
    ],
)
def test_initial_claim_rejects_any_signed_provenance_mismatch(monkeypatch, field, replacement):
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    raw = _authorization(monkeypatch, token_id=42, expires_at=expires_at)
    token = SimpleNamespace(id=42, expires_at=expires_at.replace(tzinfo=None))
    supplied = dict(BINDING)
    supplied[field] = replacement

    with pytest.raises(HTTPException) as exc:
        enrollment_router._verify_initial_fresh_install_authorization(
            token=token,
            authorization_value=raw,
            binding=supplied,
        )
    assert exc.value.status_code == 409
    assert "release-binding" in str(exc.value.detail)


def test_initial_claim_rejects_authorization_for_another_enrollment_token(monkeypatch):
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    raw = _authorization(monkeypatch, token_id=41, expires_at=expires_at)
    token = SimpleNamespace(id=42, expires_at=expires_at.replace(tzinfo=None))

    with pytest.raises(HTTPException) as exc:
        enrollment_router._verify_initial_fresh_install_authorization(
            token=token,
            authorization_value=raw,
            binding=dict(BINDING),
        )
    assert exc.value.status_code == 401
    assert "matcher ikke installationskoden" in str(exc.value.detail)


def test_receipt_hash_commits_resume_proof_to_exact_release_binding_without_new_database_authority():
    resume_proof = "resume-proof-value"
    receipt = SimpleNamespace(
        resume_proof_hash=enrollment_router._bound_resume_proof_hash(resume_proof, dict(BINDING))
    )
    enrollment_router._require_bound_resume_receipt(
        receipt,
        resume_proof=resume_proof,
        binding=dict(BINDING),
    )

    wrong = dict(BINDING)
    wrong["bundle_sha256"] = "d" * 64
    with pytest.raises(HTTPException) as exc:
        enrollment_router._require_bound_resume_receipt(
            receipt,
            resume_proof=resume_proof,
            binding=wrong,
        )
    assert exc.value.status_code == 401


def test_legacy_unbound_receipt_fails_closed_instead_of_bypassing_release_binding():
    resume_proof = "resume-proof-value"
    receipt = SimpleNamespace(resume_proof_hash=enrollment_router._resume_proof_hash(resume_proof))
    with pytest.raises(HTTPException) as exc:
        enrollment_router._require_bound_resume_receipt(
            receipt,
            resume_proof=resume_proof,
            binding=dict(BINDING),
        )
    assert exc.value.status_code == 409
    assert "legacy" in str(exc.value.detail)


def test_consuming_claim_rejects_mismatched_binding_without_client_or_token_mutation(monkeypatch):
    class QueryResult:
        def __init__(self, value, mode: str):
            self.value = value
            self.mode = mode

        def all(self):
            assert self.mode == "all"
            return [self.value]

        def one(self):
            assert self.mode == "one"
            return self.value

    class FakeSession:
        def __init__(self, token):
            self.token = token
            self.exec_count = 0
            self.added = []
            self.flush_count = 0
            self.commit_count = 0

        def get(self, _model, _key):
            return None

        def exec(self, _statement):
            self.exec_count += 1
            if self.exec_count == 1:
                return QueryResult(self.token, "all")
            if self.exec_count == 2:
                return QueryResult(self.token, "one")
            raise AssertionError("Trust-gate rejection should stop before later database queries")

        def add(self, value):
            self.added.append(value)

        def flush(self):
            self.flush_count += 1

        def commit(self):
            self.commit_count += 1

    _set_key(monkeypatch)
    token_id = 42
    expires_at = enrollment_router.utcnow() + timedelta(hours=1)
    raw = _authorization(monkeypatch, token_id=token_id, expires_at=expires_at)
    token = SimpleNamespace(
        id=token_id,
        code_hash="hashed-code",
        expires_at=expires_at,
        used_at=None,
        revoked_at=None,
        used_by_client_id=None,
        organization_id=None,
    )
    session = FakeSession(token)
    seed = bytes(range(32))
    install_id = str(uuid.uuid4())
    supplied_binding = dict(BINDING)
    supplied_binding["bundle_sha256"] = "d" * 64
    request_data = enrollment_router.EnrollmentClaimRequest(
        enrollment_code="CF-TEST-TEST-TEST",
        fresh_install_authorization=raw,
        fresh_install_binding=enrollment_router.FreshInstallClaimBinding(**supplied_binding),
        install_id=install_id,
        credential_seed_b64=base64.urlsafe_b64encode(seed).rstrip(b"=").decode("ascii"),
        resume_proof=enrollment_router._derive_resume_proof(seed, install_id),
        system_encryption_public_key_pem="x" * 128,
        update_auth_public_key_pem="x" * 80,
    )

    monkeypatch.setattr(enrollment_router, "enforce_request_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(enrollment_router, "verify_password", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(enrollment_router, "_canonical_public_key", lambda _value: ("system-public", "system-key"))
    monkeypatch.setattr(
        enrollment_router,
        "canonical_update_public_key",
        lambda _value: ("update-public", "update-key", {}, "thumbprint"),
    )

    with pytest.raises(HTTPException) as exc:
        enrollment_router.claim_enrollment_token(SimpleNamespace(), request_data, session)
    assert exc.value.status_code == 409
    assert session.added == []
    assert session.flush_count == 0
    assert session.commit_count == 0
    assert token.used_at is None
    assert token.used_by_client_id is None


def test_claim_and_complete_require_binding_but_claim_one_time_authorities_are_optional_for_receipt_resume():
    claim_fields = enrollment_router.EnrollmentClaimRequest.model_fields
    complete_fields = enrollment_router.EnrollmentCompleteRequest.model_fields
    assert claim_fields["fresh_install_binding"].is_required()
    assert not claim_fields["enrollment_code"].is_required()
    assert not claim_fields["fresh_install_authorization"].is_required()
    assert complete_fields["fresh_install_binding"].is_required()
