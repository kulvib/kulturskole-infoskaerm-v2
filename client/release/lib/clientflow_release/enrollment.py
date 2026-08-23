from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlparse
import uuid
from typing import Any

from .constants import DOMAIN_NAMES
from .filesystem import atomic_write_json, ensure_real_directory, fsync_directory


class EnrollmentError(RuntimeError):
    pass


class EnrollmentHTTPError(EnrollmentError):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = int(status_code)
        self.detail = str(detail)
        super().__init__(f"Enrollment blev afvist med HTTP {self.status_code}: {self.detail}")


_RELEASE_ID_RE = re.compile(r"^clientflow-(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-seq-([1-9]\d*)$")
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_APPROVAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,199}$")
_FRESH_INSTALL_BINDING_KEYS = {
    "release_id",
    "version",
    "release_sequence",
    "bundle_sha256",
    "bundle_size",
    "release_approval_reference",
    "release_candidate_sha256",
    "source_commit",
}


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def derive_resume_proof(seed: bytes, install_id: str) -> str:
    normalized = str(uuid.UUID(install_id))
    return _encode(hmac.new(seed, f"clientflow-enrollment-resume-v1:{normalized}".encode(), hashlib.sha256).digest())


def derive_domain_secret(seed: bytes, *, client_id: int, credential_id: str, domain: str) -> str:
    normalized = str(uuid.UUID(credential_id))
    context = f"clientflow-domain-secret-v1:{client_id}:{normalized}:{domain}".encode()
    return f"cf_{domain}_{_encode(hmac.new(seed, context, hashlib.sha256).digest())}"


def validate_backend_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise EnrollmentError("backend_url skal være en ren HTTPS-origin")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise EnrollmentError("backend_url må ikke indeholde path, query eller fragment")
    return url


def validate_fresh_install_binding(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _FRESH_INSTALL_BINDING_KEYS:
        raise EnrollmentError("Fresh-install release-binding har forkert schema")
    release_id = str(value.get("release_id") or "").strip()
    version = str(value.get("version") or "").strip()
    try:
        release_sequence = int(value.get("release_sequence"))
        bundle_size = int(value.get("bundle_size"))
    except (TypeError, ValueError) as exc:
        raise EnrollmentError("Fresh-install release-binding har ugyldige talfelter") from exc
    bundle_sha256 = str(value.get("bundle_sha256") or "").strip().lower()
    approval_reference = str(value.get("release_approval_reference") or "").strip()
    candidate_sha256 = str(value.get("release_candidate_sha256") or "").strip().lower()
    source_commit = str(value.get("source_commit") or "").strip().lower()

    if not _RELEASE_ID_RE.fullmatch(release_id) or not _VERSION_RE.fullmatch(version):
        raise EnrollmentError("Fresh-install release-binding har ugyldig release-identitet")
    if release_id != f"clientflow-{version}-seq-{release_sequence}":
        raise EnrollmentError("Fresh-install release-binding release-identitet matcher ikke")
    if release_sequence < 1 or bundle_size < 1:
        raise EnrollmentError("Fresh-install release-binding har ugyldige talfelter")
    if not _SHA256_RE.fullmatch(bundle_sha256) or not _SHA256_RE.fullmatch(candidate_sha256):
        raise EnrollmentError("Fresh-install release-binding mangler gyldig SHA-256")
    if not _APPROVAL_RE.fullmatch(approval_reference):
        raise EnrollmentError("Fresh-install release-binding mangler gyldig approval-reference")
    if not _SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise EnrollmentError("Fresh-install release-binding mangler gyldigt source commit")
    return {
        "release_id": release_id,
        "version": version,
        "release_sequence": release_sequence,
        "bundle_sha256": bundle_sha256,
        "bundle_size": bundle_size,
        "release_approval_reference": approval_reference,
        "release_candidate_sha256": candidate_sha256,
        "source_commit": source_commit,
    }


def _post_json(url: str, payload: dict[str, Any], *, ca_file: Path | None, timeout: int = 30) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "ClientFlow-Installer"},
    )
    context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise EnrollmentError("Enrollment-responsen er for stor")
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise EnrollmentHTTPError(exc.code, detail) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise EnrollmentError(f"Enrollment-transport fejlede: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnrollmentError("Enrollment-responsen er ugyldig JSON") from exc
    if not isinstance(value, dict):
        raise EnrollmentError("Enrollment-responsen skal være et objekt")
    return value


def generate_system_key(private_key: Path) -> tuple[str, str]:
    ensure_real_directory(private_key.parent, mode=0o700)
    temporary = private_key.parent / f".{private_key.name}.{os.getpid()}.new"
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(temporary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise EnrollmentError("Systemets RSA-nøgle kunne ikke genereres")
    os.chmod(temporary, 0o600)
    public = subprocess.run(
        ["openssl", "pkey", "-in", str(temporary), "-pubout"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    der = subprocess.run(
        ["openssl", "pkey", "-in", str(temporary), "-pubout", "-outform", "DER"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    if public.returncode != 0 or der.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise EnrollmentError("Systemets RSA-public key kunne ikke udledes")
    os.replace(temporary, private_key)
    fsync_directory(private_key.parent)
    return public.stdout.decode("ascii"), hashlib.sha256(der.stdout).hexdigest()[:32]


def host_facts() -> dict[str, Any]:
    machine_id = ""
    try:
        machine_id = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    ubuntu_version = ""
    try:
        values = {}
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
        ubuntu_version = values.get("VERSION_ID", "")
    except OSError:
        pass
    return {
        "hostname": socket.gethostname(),
        "machine_id": machine_id or None,
        "ubuntu_version": ubuntu_version or None,
        "uptime": None,
    }


def claim(
    *,
    backend_url: str,
    enrollment_code: str | None,
    fresh_install_authorization: str | None,
    fresh_install_binding: dict[str, Any],
    install_id: str,
    seed: bytes,
    public_key_pem: str,
    update_auth_public_key_pem: str,
    name: str | None,
    locality: str | None,
    ca_file: Path | None,
) -> dict[str, Any]:
    backend = validate_backend_url(backend_url)
    binding = validate_fresh_install_binding(fresh_install_binding)
    facts = host_facts()
    payload = {
        "enrollment_code": (str(enrollment_code).strip().upper() if enrollment_code else None),
        "fresh_install_authorization": (
            str(fresh_install_authorization).strip() if fresh_install_authorization else None
        ),
        "fresh_install_binding": binding,
        "install_id": str(uuid.UUID(install_id)),
        "credential_seed_b64": _encode(seed),
        "resume_proof": derive_resume_proof(seed, install_id),
        "system_encryption_public_key_pem": public_key_pem,
        "update_auth_public_key_pem": update_auth_public_key_pem,
        "name": name,
        "locality": locality,
        **facts,
    }
    response = _post_json(f"{backend}/api/enrollment/claim", payload, ca_file=ca_file)
    required = {"client_id", "credentials", "root_terminal_broker", "system_encryption_key_id", "update_auth"}
    if not required.issubset(response):
        raise EnrollmentError("Enrollment-responsen mangler obligatoriske felter")
    rows = response.get("credentials")
    if not isinstance(rows, list) or {str(row.get("domain")) for row in rows if isinstance(row, dict)} != set(DOMAIN_NAMES):
        raise EnrollmentError("Enrollment-responsen mangler de seks domænecredentials")
    for row in rows:
        if not isinstance(row, dict):
            raise EnrollmentError("Enrollment-responsen indeholder en ugyldig domænecredential")
        token_issuer = str(row.get("token_issuer") or "").strip()
        if not token_issuer or len(token_issuer) > 200:
            raise EnrollmentError("Enrollment-responsen mangler token issuer for et domæne")
    return response


def persist_enrollment(
    response: dict[str, Any],
    *,
    seed: bytes,
    backend_url: str,
    kiosk_user: str,
    etc_root: Path,
    private_key: Path,
    update_private_key: Path,
    tls_ca_file: str | None = None,
) -> None:
    client_id = int(response["client_id"])
    credentials_root = etc_root / "credentials"
    ensure_real_directory(etc_root, mode=0o750)
    ensure_real_directory(credentials_root, mode=0o700)
    for row in response["credentials"]:
        domain = str(row["domain"])
        credential_id = str(uuid.UUID(str(row["credential_id"])))
        token_issuer = str(row.get("token_issuer") or "").strip()
        if not token_issuer or len(token_issuer) > 200:
            raise EnrollmentError(f"Enrollment credential for {domain} mangler token issuer")
        secret = derive_domain_secret(seed, client_id=client_id, credential_id=credential_id, domain=domain)
        credential = {
            "schema_version": 1,
            "backend_url": validate_backend_url(backend_url),
            "client_id": client_id,
            "domain": domain,
            "credential_id": credential_id,
            "client_secret": secret,
            "token_issuer": token_issuer,
        }
        if tls_ca_file:
            credential["tls_ca_file"] = tls_ca_file
        atomic_write_json(credentials_root / f"{domain}.json", credential, mode=0o600)
    root = response["root_terminal_broker"]
    terminal_credential_id = str(uuid.UUID(str(root["terminal_credential_id"])))
    atomic_write_json(
        etc_root / "identity.json",
        {
            "schema_version": 1,
            "client_id": client_id,
            "terminal_credential_id": terminal_credential_id,
            "kiosk_user": kiosk_user,
        },
        mode=0o600,
    )
    update_auth = response.get("update_auth")
    if not isinstance(update_auth, dict):
        raise EnrollmentError("Enrollment-responsen mangler update-auth identity")
    update_credential_id = str(uuid.UUID(str(update_auth.get("credential_id"))))
    update_key_id = str(update_auth.get("key_id") or "").strip()
    if update_auth.get("algorithm") != "Ed25519" or not update_key_id or len(update_key_id) > 64:
        raise EnrollmentError("Enrollment update-auth kontrakten er ugyldig")
    from .update_auth import public_material
    _update_public_pem, local_update_key_id, _jwk, _jkt = public_material(update_private_key)
    if local_update_key_id != update_key_id:
        raise EnrollmentError("Backendens update key ID matcher ikke den lokale private key")
    update_root = etc_root / "update"
    ensure_real_directory(update_root, mode=0o700)
    atomic_write_json(
        update_root / "credential.json",
        {
            "schema_version": 1,
            "backend_url": validate_backend_url(backend_url),
            "client_id": client_id,
            "credential_id": update_credential_id,
            "key_id": update_key_id,
            "algorithm": "Ed25519",
            "token_audience": str(update_auth.get("token_audience") or ""),
            "access_token_issuer": str(update_auth.get("access_token_issuer") or ""),
            "access_token_audience": str(update_auth.get("access_token_audience") or ""),
            **({"tls_ca_file": tls_ca_file} if tls_ca_file else {}),
        },
        mode=0o600,
    )
    ensure_real_directory(etc_root / "root-terminal", mode=0o700)
    atomic_write_json(
        etc_root / "root-terminal/root-grant.json",
        {
            "schema_version": 1,
            "key_id": root["key_id"],
            "algorithm": root["algorithm"],
            "audience": root["audience"],
            "issuer": root["issuer"],
            "verification_key_b64": root["verification_key_b64"],
        },
        mode=0o600,
    )
    if not private_key.is_file() or private_key.stat().st_mode & 0o077:
        raise EnrollmentError("Systemets private key mangler eller har usikre rettigheder")
    if response["system_encryption_key_id"] != _system_key_id(private_key):
        raise EnrollmentError("Backendens system key ID matcher ikke den lokale private key")


def _system_key_id(private_key: Path) -> str:
    result = subprocess.run(
        ["openssl", "pkey", "-in", str(private_key), "-pubout", "-outform", "DER"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise EnrollmentError("System key ID kunne ikke beregnes")
    return hashlib.sha256(result.stdout).hexdigest()[:32]


def complete(
    *,
    backend_url: str,
    install_id: str,
    seed: bytes,
    fresh_install_binding: dict[str, Any],
    ca_file: Path | None,
) -> dict[str, Any]:
    backend = validate_backend_url(backend_url)
    binding = validate_fresh_install_binding(fresh_install_binding)
    return _post_json(
        f"{backend}/api/enrollment/complete",
        {
            "install_id": str(uuid.UUID(install_id)),
            "resume_proof": derive_resume_proof(seed, install_id),
            "fresh_install_binding": binding,
        },
        ca_file=ca_file,
    )
