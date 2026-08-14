from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any
import uuid

import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .models import ClientDomainCredential, User


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    salt = secrets.token_bytes(16)
    n, r, p = 2**14, 8, 1
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        name, n, r, p, salt, expected = encoded.split("$", 5)
        if name != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(expected)),
        )
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


def credential_digest(secret: str) -> str:
    return hmac.new(
        settings.credential_pepper.encode("utf-8"),
        secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def new_credential_secret() -> str:
    return "cf_livestream_" + secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_user_session(user: User) -> str:
    now = _now()
    claims = {
        "iss": settings.token_issuer,
        "sub": f"user:{user.id}",
        "principal": "user",
        "user_id": user.id,
        "organization_id": user.organization_id,
        "role": user.role,
        "aud": "clientflow-control",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.session_ttl_seconds)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_user_session(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="clientflow-control",
            issuer=settings.token_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from exc
    if claims.get("principal") != "user":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session principal")
    return claims


def create_client_token(credential: ClientDomainCredential) -> tuple[str, datetime]:
    now = _now()
    expires_at = now + timedelta(seconds=settings.client_token_ttl_seconds)
    audience = f"clientflow-domain:{credential.domain}"
    scope = f"clientflow:{credential.domain}"
    claims = {
        "iss": settings.token_issuer,
        "sub": f"client:{credential.client_id}:{credential.id}",
        "principal": "client_domain",
        "client_id": credential.client_id,
        "credential_id": credential.id,
        "domain": credential.domain,
        "scope": scope,
        "aud": audience,
        "token_version": credential.token_version,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256"), expires_at


def decode_client_token(token: str, *, expected_domain: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=f"clientflow-domain:{expected_domain}",
            issuer=settings.token_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid client token") from exc
    if (
        claims.get("principal") != "client_domain"
        or claims.get("domain") != expected_domain
        or claims.get("scope") != f"clientflow:{expected_domain}"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wrong client domain")
    return claims


def require_user(request: Request, db: Session) -> User:
    token = request.cookies.get("cf_session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    claims = decode_user_session(token)
    user = db.get(User, int(claims["user_id"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")
    return user


def require_client_credential(db: Session, authorization: str | None, *, domain: str) -> tuple[ClientDomainCredential, dict[str, Any]]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    claims = decode_client_token(authorization[7:].strip(), expected_domain=domain)
    credential = db.get(ClientDomainCredential, str(claims.get("credential_id") or ""))
    if (
        credential is None
        or credential.revoked_at is not None
        or credential.domain != domain
        or credential.client_id != int(claims.get("client_id") or 0)
        or credential.token_version != int(claims.get("token_version") or -1)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credential is revoked or stale")
    return credential, claims
