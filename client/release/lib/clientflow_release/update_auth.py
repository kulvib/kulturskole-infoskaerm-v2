"""Client-side Ed25519 helpers for the stable ClientFlow update identity.

Only OpenSSL is required on the client.  The private key is generated locally
and is never sent to the backend.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, urlunsplit
import uuid

from .filesystem import ensure_real_directory, fsync_directory

UPDATE_ALGORITHM = "Ed25519"
UPDATE_CLIENT_ASSERTION_TYP = "clientflow-update-client-auth+jwt"
UPDATE_DPOP_TYP = "dpop+jwt"
UPDATE_KEY_ROTATION_TYP = "clientflow-update-key-rotation+jwt"
UPDATE_TOKEN_AUDIENCE = "urn:planiq:clientflow-update:token"
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


class UpdateAuthError(RuntimeError):
    pass


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _json_b64(value: dict) -> str:
    return _b64url(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _run_openssl(args: list[str], *, timeout: int = 30) -> bytes:
    import subprocess

    result = subprocess.run(
        ["openssl", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise UpdateAuthError("OpenSSL update-auth operation fejlede")
    return result.stdout


def _public_material(private_key: Path) -> tuple[str, str, dict[str, str], str]:
    public_pem = _run_openssl(["pkey", "-in", str(private_key), "-pubout"]).decode("ascii")
    der = _run_openssl(["pkey", "-in", str(private_key), "-pubout", "-outform", "DER"])
    if len(der) != len(_ED25519_SPKI_PREFIX) + 32 or not der.startswith(_ED25519_SPKI_PREFIX):
        raise UpdateAuthError("Update public key er ikke canonical Ed25519 SPKI")
    raw = der[len(_ED25519_SPKI_PREFIX):]
    key_id = hashlib.sha256(der).hexdigest()[:32]
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw)}
    thumbprint = _b64url(
        hashlib.sha256(
            json.dumps(
                {"crv": "Ed25519", "kty": "OKP", "x": jwk["x"]},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).digest()
    )
    return public_pem, key_id, jwk, thumbprint


def generate_update_key(private_key: Path) -> tuple[str, str, dict[str, str], str]:
    ensure_real_directory(private_key.parent, mode=0o700)
    temporary = private_key.parent / f".{private_key.name}.{os.getpid()}.new"
    temporary.unlink(missing_ok=True)
    try:
        _run_openssl(["genpkey", "-algorithm", "ED25519", "-out", str(temporary)], timeout=60)
        os.chmod(temporary, 0o600)
        os.replace(temporary, private_key)
        fsync_directory(private_key.parent)
        return _public_material(private_key)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def public_material(private_key: Path) -> tuple[str, str, dict[str, str], str]:
    if not private_key.is_file() or private_key.stat().st_mode & 0o077:
        raise UpdateAuthError("Update private key mangler eller har usikre rettigheder")
    return _public_material(private_key)


def _sign(private_key: Path, signing_input: bytes) -> bytes:
    import subprocess

    if not private_key.is_file() or private_key.stat().st_mode & 0o077:
        raise UpdateAuthError("Update private key mangler eller har usikre rettigheder")
    with tempfile.NamedTemporaryFile(prefix="clientflow-update-jwt-", delete=True) as message:
        os.chmod(message.name, 0o600)
        message.write(signing_input)
        message.flush()
        result = subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private_key), "-in", message.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    if result.returncode != 0 or len(result.stdout) != 64:
        raise UpdateAuthError("Update JWT kunne ikke signeres med Ed25519")
    return result.stdout


def sign_jwt(private_key: Path, *, header: dict, claims: dict) -> str:
    encoded_header = _json_b64(header)
    encoded_claims = _json_b64(claims)
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    return f"{encoded_header}.{encoded_claims}.{_b64url(_sign(private_key, signing_input))}"


def build_client_assertion(
    private_key: Path,
    *,
    credential_id: str,
    key_id: str,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(timezone.utc)
    expires = current + timedelta(seconds=60)
    claims = {
        "iss": str(uuid.UUID(credential_id)),
        "sub": str(uuid.UUID(credential_id)),
        "aud": UPDATE_TOKEN_AUDIENCE,
        "iat": int(current.timestamp()),
        "nbf": int(current.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return sign_jwt(
        private_key,
        header={"alg": "EdDSA", "kid": key_id, "typ": UPDATE_CLIENT_ASSERTION_TYP},
        claims=claims,
    )


def canonical_htu(url: str) -> str:
    parsed = urlsplit(str(url))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def build_dpop_proof(
    private_key: Path,
    *,
    method: str,
    url: str,
    access_token: str | None = None,
    now: datetime | None = None,
) -> str:
    _pem, _key_id, jwk, _thumbprint = public_material(private_key)
    current = now or datetime.now(timezone.utc)
    claims = {
        "jti": str(uuid.uuid4()),
        "htm": str(method).upper(),
        "htu": canonical_htu(url),
        "iat": int(current.timestamp()),
    }
    if access_token is not None:
        claims["ath"] = _b64url(hashlib.sha256(access_token.encode("ascii")).digest())
    return sign_jwt(
        private_key,
        header={"alg": "EdDSA", "typ": UPDATE_DPOP_TYP, "jwk": jwk},
        claims=claims,
    )


def build_key_rotation_proof(
    private_key: Path,
    *,
    current_credential_id: str,
    method: str,
    url: str,
    now: datetime | None = None,
) -> str:
    """Prove possession of the proposed successor update private key."""
    _pem, key_id, _jwk, _thumbprint = public_material(private_key)
    current = now or datetime.now(timezone.utc)
    return sign_jwt(
        private_key,
        header={"alg": "EdDSA", "kid": key_id, "typ": UPDATE_KEY_ROTATION_TYP},
        claims={
            "jti": str(uuid.uuid4()),
            "htm": str(method).upper(),
            "htu": canonical_htu(url),
            "iat": int(current.timestamp()),
            "current_credential_id": str(uuid.UUID(current_credential_id)),
        },
    )
