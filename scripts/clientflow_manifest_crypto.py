#!/usr/bin/env python3
"""Shared canonicalization and OpenSSL helpers for ClientFlow release manifests."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping

SIGNATURE_ALGORITHM = "rsa-pss-sha256"
SIGNATURE_FIELD = "signature"


def canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Return the exact UTF-8 byte sequence covered by the manifest signature."""
    payload = dict(manifest)
    payload.pop(SIGNATURE_FIELD, None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def public_key_id(public_key_path: Path) -> str:
    result = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", str(public_key_path), "-outform", "DER"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return hashlib.sha256(result.stdout).hexdigest()[:16]


def sign_manifest(
    manifest: Mapping[str, Any],
    private_key_path: Path,
    *,
    passphrase_file: Path | None = None,
) -> str:
    with tempfile.TemporaryDirectory(prefix="clientflow-sign-") as tmp:
        payload_path = Path(tmp) / "manifest.canonical.json"
        signature_path = Path(tmp) / "manifest.signature"
        payload_path.write_bytes(canonical_manifest_bytes(manifest))
        command = [
            "openssl", "dgst", "-sha256",
            "-sign", str(private_key_path),
            "-sigopt", "rsa_padding_mode:pss",
            "-sigopt", "rsa_pss_saltlen:digest",
            "-out", str(signature_path),
        ]
        if passphrase_file is not None:
            command.extend(["-passin", f"file:{passphrase_file}"])
        command.append(str(payload_path))
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return base64.b64encode(signature_path.read_bytes()).decode("ascii")


def verify_manifest(manifest: Mapping[str, Any], public_key_path: Path) -> None:
    if manifest.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        raise ValueError("Unsupported or missing signature_algorithm")
    expected_key_id = public_key_id(public_key_path)
    if manifest.get("signature_key_id") != expected_key_id:
        raise ValueError("Manifest signature_key_id does not match the trusted public key")
    signature = str(manifest.get(SIGNATURE_FIELD) or "").strip()
    if not signature:
        raise ValueError("Manifest signature is missing")
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
    except Exception as exc:
        raise ValueError(f"Manifest signature is not valid base64: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="clientflow-verify-") as tmp:
        payload_path = Path(tmp) / "manifest.canonical.json"
        signature_path = Path(tmp) / "manifest.signature"
        payload_path.write_bytes(canonical_manifest_bytes(manifest))
        signature_path.write_bytes(signature_bytes)
        result = subprocess.run(
            [
                "openssl", "dgst", "-sha256",
                "-verify", str(public_key_path),
                "-signature", str(signature_path),
                "-sigopt", "rsa_padding_mode:pss",
                "-sigopt", "rsa_pss_saltlen:digest",
                str(payload_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "signature verification failed").strip()
            raise ValueError(details)
