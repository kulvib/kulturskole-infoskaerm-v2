"""Short-lived DB-free browser capability for Livestream media reads.

The capability is issued only after the ordinary browser authorization and is
never a durable authority.  It permits HLS/health reads for one client for a
small bounded window so individual media requests don't re-query Postgres.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import uuid
from typing import Any

import jwt
from fastapi import HTTPException, status

from .auth import SECRET_KEY

ISSUER = "clientflow-livestream-media"
AUDIENCE = "clientflow-livestream-media"
TTL_SECONDS = min(max(15, int(os.getenv("LIVESTREAM_MEDIA_CAPABILITY_TTL_SECONDS", "45"))), 120)


def issue_livestream_media_capability(*, client_id: int, principal: object) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=TTL_SECONDS)
    principal_id = getattr(principal, "id", None)
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": f"livestream-media:{int(client_id)}",
        "purpose": "livestream_media_read",
        "client_id": int(client_id),
        "principal_id": str(principal_id) if principal_id is not None else None,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, SECRET_KEY, algorithm="HS256"), expires_at


def verify_livestream_media_capability(token: str | None, *, client_id: int) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Livestream media-capability mangler")
    try:
        claims = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "nbf", "jti", "sub", "purpose", "client_id"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ugyldig livestream media-capability") from exc
    if (
        claims.get("purpose") != "livestream_media_read"
        or int(claims.get("client_id") or 0) != int(client_id)
        or claims.get("sub") != f"livestream-media:{int(client_id)}"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Media-capability tilhører en anden klient")
    return claims


def bearer_token(authorization: str | None) -> str | None:
    value = str(authorization or "")
    return value[7:].strip() if value.lower().startswith("bearer ") else None
