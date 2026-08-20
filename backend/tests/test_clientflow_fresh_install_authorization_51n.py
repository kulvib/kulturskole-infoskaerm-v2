from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from service1.clientflow_fresh_install_auth import (  # noqa: E402
    ClientFlowFreshInstallAuthorizationError,
    issue_fresh_install_authorization,
    verify_fresh_install_authorization,
)


SNAPSHOT = {
    "target_release_id": "clientflow-1.3.0-seq-1201",
    "target_version": "1.3.0",
    "target_release_sequence": 1201,
    "bundle_sha256": "a" * 64,
    "bundle_size": 123456,
    "release_approval_reference": "51H-approved",
    "release_candidate_sha256": "b" * 64,
    "source_commit": "c" * 40,
}


def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64", key)


def test_51n_signed_authorization_round_trips_exact_release_provenance(monkeypatch):
    _set_key(monkeypatch)
    now = datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc)
    token = issue_fresh_install_authorization(
        enrollment_token_id=42,
        expires_at=now + timedelta(hours=1),
        snapshot=SNAPSHOT,
    )
    result = verify_fresh_install_authorization(token, enrollment_token_id=42, now=now)
    assert result.release_id == SNAPSHOT["target_release_id"]
    assert result.version == SNAPSHOT["target_version"]
    assert result.release_sequence == SNAPSHOT["target_release_sequence"]
    assert result.bundle_sha256 == SNAPSHOT["bundle_sha256"]
    assert result.bundle_size == SNAPSHOT["bundle_size"]
    assert result.approval_reference == SNAPSHOT["release_approval_reference"]
    assert result.candidate_sha256 == SNAPSHOT["release_candidate_sha256"]
    assert result.source_commit == SNAPSHOT["source_commit"]


def test_51n_authorization_rejects_tampering_wrong_enrollment_and_expiry(monkeypatch):
    _set_key(monkeypatch)
    now = datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc)
    token = issue_fresh_install_authorization(
        enrollment_token_id=42,
        expires_at=now + timedelta(minutes=5),
        snapshot=SNAPSHOT,
    )
    prefix, payload, signature = token.split(".")
    tampered_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    with pytest.raises(ClientFlowFreshInstallAuthorizationError):
        verify_fresh_install_authorization(
            f"{prefix}.{tampered_payload}.{signature}",
            enrollment_token_id=42,
            now=now,
        )
    with pytest.raises(ClientFlowFreshInstallAuthorizationError, match="matcher ikke installationskoden"):
        verify_fresh_install_authorization(token, enrollment_token_id=43, now=now)
    with pytest.raises(ClientFlowFreshInstallAuthorizationError, match="udløbet"):
        verify_fresh_install_authorization(
            token,
            enrollment_token_id=42,
            now=now + timedelta(minutes=6),
        )


def test_51n_signing_key_is_explicit_and_exactly_32_bytes(monkeypatch):
    monkeypatch.delenv("CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64", raising=False)
    now = datetime.now(timezone.utc)
    with pytest.raises(ClientFlowFreshInstallAuthorizationError, match="ikke konfigureret"):
        issue_fresh_install_authorization(
            enrollment_token_id=42,
            expires_at=now + timedelta(hours=1),
            snapshot=SNAPSHOT,
        )
    monkeypatch.setenv(
        "CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64",
        base64.urlsafe_b64encode(b"short").decode("ascii"),
    )
    with pytest.raises(ClientFlowFreshInstallAuthorizationError, match="præcis 32 bytes"):
        issue_fresh_install_authorization(
            enrollment_token_id=42,
            expires_at=now + timedelta(hours=1),
            snapshot=SNAPSHOT,
        )
