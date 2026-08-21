"""Configuration authority for the stable ClientFlow updater bootstrap plane."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import uuid

from .enrollment import validate_backend_url
from .filesystem import FilesystemError, load_secure_json
from .update_auth import UPDATE_ALGORITHM, UPDATE_TOKEN_AUDIENCE, public_material


class UpdaterConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdaterConfig:
    backend_url: str
    client_id: int
    credential_id: str
    key_id: str
    private_key: Path
    state_root: Path
    ca_file: Path | None = None
    private_key_forbidden_mode_bits: int = 0o077

    @classmethod
    def from_paths(
        cls,
        *,
        credential_file: Path,
        private_key: Path,
        state_root: Path,
        ca_file_override: Path | None = None,
        credential_forbidden_mode_bits: int = 0o077,
        private_key_forbidden_mode_bits: int = 0o077,
    ) -> "UpdaterConfig":
        try:
            credential = load_secure_json(
                Path(credential_file),
                max_bytes=64 * 1024,
                forbidden_mode_bits=credential_forbidden_mode_bits,
            )
        except (OSError, FilesystemError) as exc:
            raise UpdaterConfigError("Update credential kunne ikke indlæses sikkert") from exc

        try:
            schema_version = int(credential.get("schema_version", 0))
            client_id = int(credential.get("client_id", 0))
            credential_id = str(uuid.UUID(str(credential.get("credential_id") or "")))
        except (TypeError, ValueError, AttributeError) as exc:
            raise UpdaterConfigError("Update credential identity er ugyldig") from exc
        if schema_version != 1 or client_id <= 0:
            raise UpdaterConfigError("Update credential schema/client_id er ugyldig")
        if credential.get("algorithm") != UPDATE_ALGORITHM:
            raise UpdaterConfigError("Update credential kræver Ed25519")
        if str(credential.get("token_audience") or "") != UPDATE_TOKEN_AUDIENCE:
            raise UpdaterConfigError("Update credential har forkert token audience")
        if not str(credential.get("access_token_issuer") or "").strip():
            raise UpdaterConfigError("Update credential mangler access-token issuer")
        if not str(credential.get("access_token_audience") or "").strip():
            raise UpdaterConfigError("Update credential mangler access-token audience")

        try:
            backend_url = validate_backend_url(str(credential.get("backend_url") or ""))
        except Exception as exc:
            raise UpdaterConfigError("Update credential har ugyldig backend_url") from exc

        key_path = Path(private_key)
        try:
            _pem, local_key_id, _jwk, _thumbprint = public_material(
                key_path,
                forbidden_mode_bits=private_key_forbidden_mode_bits,
            )
        except Exception as exc:
            raise UpdaterConfigError("Update private key kunne ikke valideres") from exc
        key_id = str(credential.get("key_id") or "").strip()
        if not key_id or key_id != local_key_id:
            raise UpdaterConfigError("Update credential key_id matcher ikke private key")

        ca_file: Path | None = None
        raw_ca_file = str(credential.get("tls_ca_file") or "").strip()
        if raw_ca_file:
            configured_ca_file = Path(ca_file_override) if ca_file_override is not None else Path(raw_ca_file)
            if not configured_ca_file.is_absolute():
                raise UpdaterConfigError("tls_ca_file skal være en absolut sti")
            ca_file = configured_ca_file

        return cls(
            backend_url=backend_url,
            client_id=client_id,
            credential_id=credential_id,
            key_id=key_id,
            private_key=key_path,
            state_root=Path(state_root),
            ca_file=ca_file,
            private_key_forbidden_mode_bits=private_key_forbidden_mode_bits,
        )

    @classmethod
    def from_environment(cls) -> "UpdaterConfig":
        credentials_directory = str(os.getenv("CREDENTIALS_DIRECTORY") or "").strip()
        if credentials_directory:
            credentials_root = Path(credentials_directory)
            default_credential = credentials_root / "update-credential.json"
            default_private_key = credentials_root / "update-private-key.pem"
        else:
            default_credential = Path("/etc/clientflow/update/credential.json")
            default_private_key = Path("/etc/clientflow/update/private-key.pem")

        raw_credential_override = str(os.getenv("CLIENTFLOW_UPDATE_CREDENTIAL_FILE") or "").strip()
        raw_private_key_override = str(os.getenv("CLIENTFLOW_UPDATE_PRIVATE_KEY_FILE") or "").strip()
        credential_file = Path(raw_credential_override) if raw_credential_override else default_credential
        private_key = Path(raw_private_key_override) if raw_private_key_override else default_private_key
        state_root = Path(
            os.getenv("STATE_DIRECTORY")
            or os.getenv("CLIENTFLOW_UPDATE_STATE_DIR")
            or "/var/lib/clientflow/updater"
        )
        raw_ca_override = str(os.getenv("CLIENTFLOW_UPDATE_CA_FILE") or "").strip()
        ca_file_override = Path(raw_ca_override) if raw_ca_override else None

        # systemd LoadCredential= materializes service credentials as 0440 files
        # inside CREDENTIALS_DIRECTORY.  Permit group-read only for those default
        # systemd-provided paths; ordinary/overridden credential paths retain
        # the at-rest 0600 policy.
        credential_forbidden_mode_bits = (
            0o007 if credentials_directory and not raw_credential_override else 0o077
        )
        private_key_forbidden_mode_bits = (
            0o007 if credentials_directory and not raw_private_key_override else 0o077
        )

        return cls.from_paths(
            credential_file=credential_file,
            private_key=private_key,
            state_root=state_root,
            ca_file_override=ca_file_override,
            credential_forbidden_mode_bits=credential_forbidden_mode_bits,
            private_key_forbidden_mode_bits=private_key_forbidden_mode_bits,
        )
