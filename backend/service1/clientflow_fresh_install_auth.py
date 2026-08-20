"""Immutable fresh-install authorization bound to one enrollment token.

The published ClientFlow bundle remains the only byte authority. This module
creates a short-lived signed capability that carries the exact already-verified
51M artifact identity selected when an enrollment code is created. The
capability is useful only together with that still-active enrollment code.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
from typing import Any

_AUTH_ENV = "CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64"
_TOKEN_PREFIX = "cf-fresh-v1"
_PURPOSE = "clientflow-fresh-install"
_RELEASE_ID_RE = re.compile(r"^clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ClientFlowFreshInstallAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FreshInstallAuthorization:
    enrollment_token_id: int
    expires_at_epoch: int
    release_id: str
    version: str
    release_sequence: int
    bundle_sha256: str
    bundle_size: int
    approval_reference: str
    candidate_sha256: str
    source_commit: str


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except Exception as exc:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization er ugyldig") from exc


def _signing_key() -> bytes:
    raw = str(os.getenv(_AUTH_ENV) or "").strip()
    if not raw:
        raise ClientFlowFreshInstallAuthorizationError(f"{_AUTH_ENV} er ikke konfigureret")
    key = _b64decode(raw)
    if len(key) != 32:
        raise ClientFlowFreshInstallAuthorizationError(f"{_AUTH_ENV} skal være præcis 32 bytes")
    return key


def utc_epoch(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return int(value.timestamp())


def _now_epoch(now: datetime | None = None) -> int:
    return utc_epoch(now or datetime.now(timezone.utc))


def _validated_payload(payload: dict[str, Any]) -> FreshInstallAuthorization:
    if set(payload) != {
        "schema", "purpose", "enrollment_token_id", "expires_at", "release_id",
        "version", "release_sequence", "bundle_sha256", "bundle_size",
        "approval_reference", "candidate_sha256", "source_commit",
    }:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization har forkert schema")
    if payload.get("schema") != 1 or payload.get("purpose") != _PURPOSE:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization har forkert formål")
    try:
        token_id = int(payload["enrollment_token_id"])
        expires_at = int(payload["expires_at"])
        sequence = int(payload["release_sequence"])
        bundle_size = int(payload["bundle_size"])
    except (TypeError, ValueError) as exc:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization har ugyldige talfelter") from exc
    if token_id < 1 or expires_at < 1 or sequence < 1 or bundle_size < 1:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization har ugyldige talfelter")

    release_id = str(payload["release_id"] or "").strip()
    version = str(payload["version"] or "").strip()
    bundle_sha256 = str(payload["bundle_sha256"] or "").strip().lower()
    approval_reference = str(payload["approval_reference"] or "").strip()
    candidate_sha256 = str(payload["candidate_sha256"] or "").strip().lower()
    source_commit = str(payload["source_commit"] or "").strip().lower()
    if not _RELEASE_ID_RE.fullmatch(release_id) or not _VERSION_RE.fullmatch(version):
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization har ugyldig release-identitet")
    if release_id != f"clientflow-{version}-seq-{sequence}":
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization release-identitet matcher ikke")
    if not _SHA256_RE.fullmatch(bundle_sha256) or not _SHA256_RE.fullmatch(candidate_sha256):
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization mangler gyldig SHA-256")
    if not _SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization mangler gyldigt source commit")
    if not approval_reference or len(approval_reference) > 200:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization mangler approval-reference")

    return FreshInstallAuthorization(
        enrollment_token_id=token_id,
        expires_at_epoch=expires_at,
        release_id=release_id,
        version=version,
        release_sequence=sequence,
        bundle_sha256=bundle_sha256,
        bundle_size=bundle_size,
        approval_reference=approval_reference,
        candidate_sha256=candidate_sha256,
        source_commit=source_commit,
    )


def issue_fresh_install_authorization(
    *,
    enrollment_token_id: int,
    expires_at: datetime,
    snapshot: dict[str, Any],
) -> str:
    normalized = _validated_payload({
        "schema": 1,
        "purpose": _PURPOSE,
        "enrollment_token_id": int(enrollment_token_id),
        "expires_at": utc_epoch(expires_at),
        "release_id": snapshot.get("target_release_id"),
        "version": snapshot.get("target_version"),
        "release_sequence": snapshot.get("target_release_sequence"),
        "bundle_sha256": snapshot.get("bundle_sha256"),
        "bundle_size": snapshot.get("bundle_size"),
        "approval_reference": snapshot.get("release_approval_reference"),
        "candidate_sha256": snapshot.get("release_candidate_sha256"),
        "source_commit": snapshot.get("source_commit"),
    })
    payload = {
        "schema": 1,
        "purpose": _PURPOSE,
        "enrollment_token_id": normalized.enrollment_token_id,
        "expires_at": normalized.expires_at_epoch,
        "release_id": normalized.release_id,
        "version": normalized.version,
        "release_sequence": normalized.release_sequence,
        "bundle_sha256": normalized.bundle_sha256,
        "bundle_size": normalized.bundle_size,
        "approval_reference": normalized.approval_reference,
        "candidate_sha256": normalized.candidate_sha256,
        "source_commit": normalized.source_commit,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = _b64encode(body)
    signature = hmac.new(
        _signing_key(),
        (_TOKEN_PREFIX + "." + encoded).encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{_TOKEN_PREFIX}.{encoded}.{_b64encode(signature)}"


def verify_fresh_install_authorization(
    token: str,
    *,
    enrollment_token_id: int,
    now: datetime | None = None,
) -> FreshInstallAuthorization:
    raw = str(token or "").strip()
    if not raw or len(raw) > 4096:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization mangler eller er for lang")
    parts = raw.split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization har forkert format")
    encoded, supplied_signature = parts[1], parts[2]
    expected_signature = hmac.new(
        _signing_key(),
        (_TOKEN_PREFIX + "." + encoded).encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_b64decode(supplied_signature), expected_signature):
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization-signaturen er ugyldig")
    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization payload er ugyldig") from exc
    if not isinstance(payload, dict):
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization payload er ugyldig")
    authorization = _validated_payload(payload)
    if authorization.enrollment_token_id != int(enrollment_token_id):
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization matcher ikke installationskoden")
    if authorization.expires_at_epoch < _now_epoch(now):
        raise ClientFlowFreshInstallAuthorizationError("Fresh-install authorization er udløbet")
    return authorization
