from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    jwt_secret: str
    credential_pepper: str
    token_issuer: str
    public_base_url: str
    hls_root: Path
    session_ttl_seconds: int = 12 * 60 * 60
    client_token_ttl_seconds: int = 10 * 60
    media_stale_seconds: int = 45
    command_max_attempts: int = 5

    @classmethod
    def load(cls) -> "Settings":
        database_url = _required("DATABASE_URL")
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://") :]

        jwt_secret = _required("JWT_SECRET")
        credential_pepper = _required("CREDENTIAL_PEPPER")
        if len(jwt_secret) < 32 or len(credential_pepper) < 32:
            raise RuntimeError("JWT_SECRET and CREDENTIAL_PEPPER must each be at least 32 characters")

        public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not public_base_url:
            hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
            if hostname:
                public_base_url = f"https://{hostname}"
        if not public_base_url:
            raise RuntimeError("PUBLIC_BASE_URL or RENDER_EXTERNAL_HOSTNAME is required")

        return cls(
            database_url=database_url,
            jwt_secret=jwt_secret,
            credential_pepper=credential_pepper,
            token_issuer=os.getenv("TOKEN_ISSUER", "clientflow-api").strip() or "clientflow-api",
            public_base_url=public_base_url,
            hls_root=Path(os.getenv("HLS_ROOT", "/tmp/clientflow-hls")),
            media_stale_seconds=int(os.getenv("MEDIA_STALE_SECONDS", "45")),
        )


settings = Settings.load()
