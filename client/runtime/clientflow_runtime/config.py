"""Strict credential and identity loading for isolated agents and brokers."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Any
from urllib.parse import urlparse
import uuid

from .constants import DOMAIN_VALUES, Domain


class ConfigurationError(RuntimeError):
    pass


def load_secure_json(
    path: Path,
    *,
    max_bytes: int = 256 * 1024,
    forbidden_mode_bits: int = 0o022,
) -> dict[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Konfigurationsfil mangler: {path}") from exc
    except OSError as exc:
        raise ConfigurationError(f"Konfigurationsfil kunne ikke åbnes sikkert: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ConfigurationError(f"Konfigurationsfil er ikke en almindelig fil: {path}")
        if metadata.st_size > max_bytes:
            raise ConfigurationError(f"Konfigurationsfil er for stor: {path}")
        if metadata.st_mode & forbidden_mode_bits:
            raise ConfigurationError(f"Konfigurationsfil har for brede rettigheder: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ConfigurationError(f"Konfigurationsfil er for stor: {path}")
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Konfigurationsfil er ugyldig: {path}") from exc
    finally:
        os.close(descriptor)
    if not isinstance(value, dict):
        raise ConfigurationError(f"Konfigurationsfil skal indeholde et objekt: {path}")
    return value


def _credential_path(domain: Domain) -> Path:
    explicit = os.getenv("CLIENTFLOW_CREDENTIAL_FILE")
    if explicit:
        return Path(explicit)
    directory = os.getenv("CREDENTIALS_DIRECTORY")
    if not directory:
        raise ConfigurationError("CREDENTIALS_DIRECTORY mangler")
    return Path(directory) / f"{domain.value}.json"


def _validate_backend_url(raw: object) -> str:
    value = str(raw or "").rstrip("/")
    parsed = urlparse(value)
    allow_http = os.getenv("CLIENTFLOW_ALLOW_INSECURE_HTTP") == "1"
    if parsed.scheme not in ({"http", "https"} if allow_http else {"https"}):
        raise ConfigurationError("backend_url skal bruge HTTPS")
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ConfigurationError("backend_url er ugyldig")
    return value


@dataclass(frozen=True, slots=True)
class DomainCredential:
    backend_url: str
    client_id: int
    domain: Domain
    credential_id: str
    client_secret: str
    token_issuer: str
    tls_ca_file: str | None = None

    @classmethod
    def load(cls, expected_domain: Domain) -> "DomainCredential":
        data = load_secure_json(_credential_path(expected_domain))
        if data.get("schema_version") != 1:
            raise ConfigurationError("Credential schema_version skal være 1")
        domain_raw = str(data.get("domain") or "")
        if domain_raw not in DOMAIN_VALUES or domain_raw != expected_domain.value:
            raise ConfigurationError("Credential tilhører et andet domæne")
        try:
            client_id = int(data["client_id"])
            if client_id <= 0:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError("Credential client_id er ugyldig") from exc
        credential_id = str(data.get("credential_id") or "")
        try:
            uuid.UUID(credential_id)
        except ValueError as exc:
            raise ConfigurationError("Credential credential_id er ugyldig") from exc
        secret = str(data.get("client_secret") or "")
        if len(secret) < 32:
            raise ConfigurationError("Credential secret er ugyldig")
        token_issuer = str(data.get("token_issuer") or "").strip()
        if not token_issuer or len(token_issuer) > 200:
            raise ConfigurationError("Credential token_issuer er ugyldig")
        tls_ca_file = str(data.get("tls_ca_file") or "").strip() or None
        return cls(
            backend_url=_validate_backend_url(data.get("backend_url")),
            client_id=client_id,
            domain=expected_domain,
            credential_id=credential_id,
            client_secret=secret,
            token_issuer=token_issuer,
            tls_ca_file=tls_ca_file,
        )


@dataclass(frozen=True, slots=True)
class ClientIdentity:
    client_id: int
    terminal_credential_id: str
    kiosk_user: str

    @classmethod
    def load(cls, path: Path | None = None) -> "ClientIdentity":
        selected = path or Path(os.getenv("CLIENTFLOW_IDENTITY_FILE", "/etc/clientflow/identity.json"))
        data = load_secure_json(selected)
        if data.get("schema_version") != 1:
            raise ConfigurationError("Identity schema_version skal være 1")
        try:
            client_id = int(data["client_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError("Identity client_id er ugyldig") from exc
        terminal_credential_id = str(data.get("terminal_credential_id") or "")
        try:
            uuid.UUID(terminal_credential_id)
        except ValueError as exc:
            raise ConfigurationError("Identity terminal_credential_id er ugyldig") from exc
        kiosk_user = str(data.get("kiosk_user") or "").strip()
        if not kiosk_user or not kiosk_user.replace("-", "").replace("_", "").isalnum():
            raise ConfigurationError("Identity kiosk_user er ugyldig")
        return cls(client_id=client_id, terminal_credential_id=terminal_credential_id, kiosk_user=kiosk_user)
