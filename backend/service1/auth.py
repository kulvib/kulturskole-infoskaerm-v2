import os
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.openapi.models import OAuthFlows as OAuthFlowsModel
from fastapi.security import OAuth2, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import Session, select

from .audit import add_audit_log, commit_audit_log
from .db import get_session
from .models import Client, RefreshToken, User
from .client_ip import get_client_ip
from .rate_limit import (
    assert_key_not_limited,
    clear_key_rate_limit,
    enforce_request_rate_limit,
    normalize_rate_limit_identifier,
    record_key_attempt,
)
from .observability import log_safe_exception

load_dotenv()

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "SECRET_KEY mangler eller er for kort (minimum 32 tegn). "
        "Sæt SECRET_KEY i din .env-fil."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
JWT_ISSUER = os.getenv("JWT_ISSUER", "planiq-display-api")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "planiq-display")
JWT_REQUIRED_CLAIMS = ("exp", "iat", "nbf", "jti", "iss", "aud")
IS_PRODUCTION = os.getenv("ENVIRONMENT", "production") == "production"
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
SESSION_ABSOLUTE_TIMEOUT_MINUTES = int(os.getenv("SESSION_ABSOLUTE_TIMEOUT_MINUTES", "360"))
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "refresh_token")
REFRESH_COOKIE_PATH = os.getenv("REFRESH_COOKIE_PATH", "/api/auth")
ACCESS_COOKIE_SAMESITE = os.getenv("ACCESS_COOKIE_SAMESITE", "lax").strip().lower()
if ACCESS_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    ACCESS_COOKIE_SAMESITE = "lax"
REFRESH_COOKIE_SECURE = os.getenv("REFRESH_COOKIE_SECURE", "true" if IS_PRODUCTION else "false").strip().lower() in {"1", "true", "yes", "on"}
REFRESH_COOKIE_SAMESITE = os.getenv("REFRESH_COOKIE_SAMESITE", "lax").strip().lower()
if REFRESH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    REFRESH_COOKIE_SAMESITE = "lax"


# ---------------------------------------------------------------------------
# OAuth2-skema: accepterer token fra både Authorization-header og cookie.
# Browser-frontend bør bruge HttpOnly-cookie. Authorization-header bevares til
# installerede klienter og andre machine/API-kald.
# ---------------------------------------------------------------------------
class OAuth2PasswordBearerOrCookie(OAuth2):
    def __init__(self, tokenUrl: str, auto_error: bool = True):
        flows = OAuthFlowsModel(password={"tokenUrl": tokenUrl, "scopes": {}})
        super().__init__(flows=flows, auto_error=auto_error)
        self.auto_error = auto_error

    async def __call__(self, request: Request) -> Optional[str]:
        authorization = request.headers.get("Authorization")
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:]
        token = request.cookies.get("access_token")
        if token:
            return token
        if self.auto_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None


MIN_PASSWORD_LENGTH = 12
PASSWORD_MAX_UTF8_BYTES = 72
_COMMON_PASSWORDS = {
    "password",
    "password1",
    "password12",
    "password123",
    "password123!",
    "qwerty123",
    "qwerty1234",
    "admin1234",
    "velkommen123",
    "adgangskode",
    "adgangskode123",
    "sommer2025",
    "sommer2026",
    "planiq123",
    "123456789012",
}

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearerOrCookie(tokenUrl="auth/token")


class ClientTokenRequest(BaseModel):
    client_id: int
    client_secret: str


class RefreshRequest(BaseModel):
    refresh_token: Optional[str] = None


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Password/JWT helpers
# ---------------------------------------------------------------------------
def validate_password_strength(password: str):
    """Valider adgangskode efter samme princip som Flow og Worklog.

    Vi bruger længde, bcrypt-kompatibel max-længde, blokering af kontroltegn
    og en lille liste af meget almindelige passwords. Vi kræver ikke bestemte
    tegntyper, så lange passphrases også er gyldige.
    """
    if not isinstance(password, str):
        raise HTTPException(status_code=400, detail="Adgangskode skal udfyldes")

    password_bytes = password.encode("utf-8")
    normalized = password.strip().lower()

    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Adgangskoden skal være mindst {MIN_PASSWORD_LENGTH} tegn lang.",
        )
    if len(password_bytes) > PASSWORD_MAX_UTF8_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Adgangskoden må højst være {PASSWORD_MAX_UTF8_BYTES} bytes.",
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in password):
        raise HTTPException(
            status_code=400,
            detail="Adgangskoden må ikke indeholde linjeskift eller kontroltegn.",
        )
    if normalized in _COMMON_PASSWORDS:
        raise HTTPException(
            status_code=400,
            detail="Adgangskoden er for almindelig. Vælg en mere unik adgangskode.",
        )


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(username: str, password: str, session: Session):
    identifier = (username or "").strip().lower()
    user = session.exec(
        select(User).where(
            or_(
                func.lower(User.username) == identifier,
                func.lower(User.email) == identifier,
            )
        )
    ).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def _token_version(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _coerce_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _session_expiry_iso(value: datetime) -> str:
    value = _coerce_aware_utc(value) or datetime.now(timezone.utc)
    return value.isoformat()


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    session_expires_at: Optional[datetime] = None,
):
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = data.copy()
    if session_expires_at is not None:
        to_encode["session_expires_at"] = _session_expiry_iso(session_expires_at)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "nbf": now,
        "jti": uuid.uuid4().hex,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _set_auth_cookie(response: Response, access_token: str):
    # Bagudkompatibel access-cookie til eksisterende klienter. Browserens
    # primære sessionfornyelse sker via refresh-token i HttpOnly-cookie.
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite=ACCESS_COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def _set_refresh_cookie(response: Response, refresh_token: str, max_age_seconds: int):
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite=REFRESH_COOKIE_SAMESITE,
        max_age=max(0, int(max_age_seconds)),
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response):
    # Slet både den aktuelle cookie-path og den tidligere fejlagtige /auth-path.
    # Det gør oprydningen sikker efter overgangen til Worklog-style /api/auth.
    paths = [REFRESH_COOKIE_PATH]
    if "/auth" not in paths:
        paths.append("/auth")
    for cookie_path in paths:
        response.delete_cookie(
            key=REFRESH_COOKIE_NAME,
            path=cookie_path,
            secure=REFRESH_COOKIE_SECURE,
            samesite=REFRESH_COOKIE_SAMESITE,
            httponly=True,
        )


def _get_refresh_token_from_request(request: Request, body: Optional[RefreshRequest] = None) -> Optional[str]:
    if body and body.refresh_token:
        return body.refresh_token
    return request.cookies.get(REFRESH_COOKIE_NAME)


def _refresh_token_max_age_seconds(expires_at: datetime) -> int:
    aware = _coerce_aware_utc(expires_at) or datetime.now(timezone.utc)
    remaining = aware - datetime.now(timezone.utc)
    return max(0, int(remaining.total_seconds()))


def _create_refresh_token(session: Session, user_id: int, request: Request, session_expires_at: Optional[datetime] = None) -> tuple[str, datetime, datetime]:
    token = _generate_refresh_token()
    token_hash = _hash_refresh_token(token)
    now = datetime.now(timezone.utc)
    absolute_expiry = _coerce_aware_utc(session_expires_at) or (now + timedelta(minutes=SESSION_ABSOLUTE_TIMEOUT_MINUTES))
    expires_at = min(now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), absolute_expiry)
    row = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at.replace(tzinfo=None),
        session_expires_at=absolute_expiry.replace(tzinfo=None),
        created_ip=get_client_ip(request),
        user_agent=(request.headers.get("user-agent", "") or "")[:500],
    )
    session.add(row)
    return token, expires_at, absolute_expiry


def _refresh_session_expires_at(token_row: RefreshToken) -> datetime:
    created = (
        _coerce_aware_utc(getattr(token_row, "created_at", None))
        or datetime.now(timezone.utc)
    )
    policy_expiry = created + timedelta(minutes=SESSION_ABSOLUTE_TIMEOUT_MINUTES)
    stored_expiry = _coerce_aware_utc(getattr(token_row, "session_expires_at", None))
    # Nye strammere sessionregler gælder også eksisterende tokenfamilier.
    return min(stored_expiry, policy_expiry) if stored_expiry else policy_expiry


def _revoke_all_user_refresh_tokens(session: Session, user_id: int) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all()
    for row in rows:
        row.revoked_at = now
        session.add(row)
    return len(rows)


def _decode_token_or_raise(token: str) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Kunne ikke validere legitimationsoplysninger",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            leeway=10,
            options={"require": list(JWT_REQUIRED_CLAIMS)},
        )
        raw_session_expiry = payload.get("session_expires_at")
        if raw_session_expiry:
            try:
                session_expiry = datetime.fromisoformat(str(raw_session_expiry).replace("Z", "+00:00"))
                if _coerce_aware_utc(session_expiry) < datetime.now(timezone.utc):
                    raise credentials_exception
            except HTTPException:
                raise
            except Exception:
                raise credentials_exception
        return payload
    except InvalidTokenError:
        raise credentials_exception


def validate_browser_auth_session_binding(
    session: Session,
    *,
    user_id: int,
    user_token_version: int,
    auth_session_binding: str,
) -> Optional[User]:
    """Resolve a still-active browser login session from its stable binding.

    The binding is derived from ``user_id + token_version + session_expires_at``.
    Refresh rotation preserves ``session_expires_at`` while revoking the previous
    refresh row, so any active row from the same login family can validate an
    already-established privileged WebSocket. Logout, user deactivation, token
    version changes and absolute session expiry all invalidate the binding.
    """
    binding = str(auth_session_binding or "").strip()
    if not binding:
        return None

    user = session.get(User, int(user_id))
    if (
        user is None
        or not getattr(user, "is_active", False)
        or _token_version(getattr(user, "token_version", 0)) != _token_version(user_token_version)
    ):
        return None

    now = datetime.now(timezone.utc)
    rows = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == int(user_id),
            RefreshToken.revoked_at.is_(None),
        )
    ).all()
    for row in rows:
        refresh_expiry = _coerce_aware_utc(getattr(row, "expires_at", None))
        session_expiry = _refresh_session_expires_at(row)
        if not refresh_expiry or refresh_expiry <= now or session_expiry <= now:
            continue
        stored_session_expiry = (
            _coerce_aware_utc(getattr(row, "session_expires_at", None))
            or session_expiry
        )
        material = (
            f"{int(user.id)}:{_token_version(getattr(user, 'token_version', 0))}:"
            f"{_session_expiry_iso(stored_session_expiry)}"
        )
        candidate = hashlib.sha256(material.encode("utf-8")).hexdigest()
        if secrets.compare_digest(candidate, binding):
            return user
    return None


def get_access_token_session_binding(token: str, user: User) -> str:
    """Return a stable, non-secret binding for the current browser login session.

    ``session_expires_at`` is created once at login and preserved across refresh
    rotation. Binding it with user id + token_version lets short-lived privileged
    capabilities survive normal access-token refreshes while still becoming
    invalid after logout/login, password changes or other token-version bumps.
    """
    payload = _decode_token_or_raise(token)
    if payload.get("principal") == "client":
        raise HTTPException(status_code=403, detail="Kræver bruger-token")
    if user.id is None:
        raise HTTPException(status_code=401, detail="Bruger mangler database-id")
    if str(payload.get("sub") or "") != str(user.username):
        raise HTTPException(status_code=401, detail="Sessionen matcher ikke brugeren")
    try:
        payload_user_id = int(payload.get("uid"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Sessionen mangler brugerbinding")
    if payload_user_id != int(user.id):
        raise HTTPException(status_code=401, detail="Sessionen matcher ikke brugeren")
    if _token_version(payload.get("token_version")) != _token_version(getattr(user, "token_version", 0)):
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    raw_session_expiry = str(payload.get("session_expires_at") or "").strip()
    if not raw_session_expiry:
        raise HTTPException(status_code=401, detail="Sessionen mangler sikkerhedsbinding")
    material = f"{int(user.id)}:{_token_version(getattr(user, 'token_version', 0))}:{raw_session_expiry}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def require_active_browser_auth_session_binding(
    session: Session,
    *,
    token: str,
    user: User,
) -> str:
    """Require that an access token still belongs to an active login family.

    Access JWTs are intentionally stateless and can remain cryptographically
    valid for a short period after logout/revocation. Privileged browser
    capabilities such as Terminal and Remote Desktop must therefore verify the
    stable login-session binding against the active refresh-token family before
    issuing a new one-time WebSocket ticket.
    """
    binding = get_access_token_session_binding(token, user)
    if user.id is None:
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    active_user = validate_browser_auth_session_binding(
        session,
        user_id=int(user.id),
        user_token_version=_token_version(getattr(user, "token_version", 0)),
        auth_session_binding=binding,
    )
    if active_user is None:
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    return binding


def _user_from_payload(payload: dict, session: Session) -> User:
    if payload.get("principal") == "client":
        raise HTTPException(status_code=403, detail="Kræver bruger-token")
    username: str = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Ugyldigt bruger-token")
    user = session.exec(select(User).where(User.username == username)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Inaktiv eller ukendt bruger")
    if _token_version(payload.get("token_version")) != _token_version(getattr(user, "token_version", 0)):
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    return user


def _client_from_payload(payload: dict, session: Session) -> Client:
    if payload.get("principal") != "client":
        raise HTTPException(status_code=403, detail="Kræver klient-token")
    client_id = payload.get("client_id")
    if client_id is None:
        raise HTTPException(status_code=401, detail="Ugyldigt klient-token")
    try:
        client_id_int = int(client_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Ugyldigt klient-token")
    client = session.get(Client, client_id_int)
    if (
        not client
        or client.client_secret_revoked_at is not None
        or getattr(client, "deleted_at", None) is not None
        or str(getattr(client, "status", "") or "").lower() == "deleted"
    ):
        raise HTTPException(status_code=401, detail="Klienten er ukendt eller revoked")
    if _token_version(payload.get("client_token_version")) != _token_version(getattr(client, "client_token_version", 0)):
        raise HTTPException(status_code=401, detail="Klient-sessionen er ikke længere gyldig")
    return client


def _user_response(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": getattr(user, "role", "bruger"),
        "full_name": user.full_name,
        "remarks": user.remarks,
        "organization_id": user.organization_id,
        "email": user.email,
        "must_change_password": user.must_change_password,
    }


@router.post("/token")
def login_for_access_token(
    response: Response,
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    invalid_credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Forkert brugernavn eller kodeord",
        headers={"WWW-Authenticate": "Bearer"},
    )

    client_ip = get_client_ip(request)
    raw_identifier = (form_data.username or "").strip()
    identifier_key = normalize_rate_limit_identifier(raw_identifier)
    enforce_request_rate_limit(
        request,
        bucket="auth-login-ip",
        max_attempts=20,
        window_seconds=60,
        detail="For mange loginforsøg. Prøv igen senere.",
    )
    assert_key_not_limited(
        bucket="auth-login-account",
        key=identifier_key,
        max_attempts=10,
        window_seconds=60,
        detail="For mange mislykkede loginforsøg. Prøv igen senere.",
    )

    user = authenticate_user(raw_identifier, form_data.password, session)

    if not user:
        candidate = session.exec(
            select(User).where(
                or_(
                    func.lower(User.username) == raw_identifier.lower(),
                    func.lower(User.email) == raw_identifier.lower(),
                )
            )
        ).first() if raw_identifier else None
        commit_audit_log(
            session,
            action="login_failed",
            request=request,
            target_user=candidate,
            entity_type="user",
            entity_id=getattr(candidate, "id", None),
            entity_label=getattr(candidate, "username", None) or raw_identifier[:120],
            status="failed",
            details={"reason": "wrong_password" if candidate else "unknown_user"},
        )
        record_key_attempt(bucket="auth-login-account", key=identifier_key, window_seconds=60)
        raise invalid_credentials_exception

    if not user.is_active:
        commit_audit_log(
            session,
            action="login_failed",
            request=request,
            target_user=user,
            entity_type="user",
            entity_id=user.id,
            entity_label=user.username,
            status="failed",
            details={"reason": "inactive_user"},
        )
        record_key_attempt(bucket="auth-login-account", key=identifier_key, window_seconds=60)
        raise invalid_credentials_exception

    clear_key_rate_limit(bucket="auth-login-account", key=identifier_key)

    previous_last_login_at = getattr(user, "last_login_at", None)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.last_login_ip = client_ip

    refresh_token, refresh_expires_at, session_expires_at = _create_refresh_token(session, user.id, request)
    access_token = create_access_token(data={
        "sub": user.username,
        "uid": user.id,
        "role": getattr(user, "role", "bruger"),
        "token_version": _token_version(getattr(user, "token_version", 0)),
    }, session_expires_at=session_expires_at)
    login_audit = add_audit_log(
        session,
        action="login_success",
        request=request,
        actor=user,
        target_user=user,
        entity_type="user",
        entity_id=user.id,
        entity_label=user.username,
        details={
            "previous_last_login_at": previous_last_login_at.isoformat() if previous_last_login_at else None,
            "must_change_password": user.must_change_password,
        },
    )

    try:
        session.add(user)
        # Flush tildeler audit-loggens id før commit. Login, refresh-token,
        # last_login og audit-række bevares fortsat i samme transaktion.
        session.flush()
        login_audit_id = login_audit.id
        session.commit()
    except Exception as exc:
        session.rollback()
        log_safe_exception(
            logger,
            exc,
            event="login_transaction_failed",
            user_id=user.id,
            location="auth.login_for_access_token",
        )
        raise HTTPException(status_code=500, detail="Kunne ikke gennemføre login")

    logger.info(
        "login_success_audit_persisted user_id=%s audit_log_id=%s",
        user.id,
        login_audit_id,
    )

    _set_auth_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token, _refresh_token_max_age_seconds(refresh_expires_at))

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "session_expires_at": _session_expiry_iso(session_expires_at),
        "user": _user_response(user),
    }


@router.post("/client-token")
def login_for_client_token(
    request: Request,
    data: ClientTokenRequest = Body(...),
    session: Session = Depends(get_session),
):
    enforce_request_rate_limit(
        request,
        bucket="auth-client-token",
        max_attempts=30,
        window_seconds=60,
        detail="For mange client-token forsøg. Prøv igen senere.",
    )

    client = session.get(Client, data.client_id)
    if (
        not client
        or not client.client_secret_hash
        or client.client_secret_revoked_at is not None
        or getattr(client, "deleted_at", None) is not None
        or str(getattr(client, "status", "") or "").lower() == "deleted"
        or not verify_password(data.client_secret, client.client_secret_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ugyldig client_id eller client_secret",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={
        "sub": f"client:{client.id}",
        "principal": "client",
        "client_id": client.id,
        "role": "client",
        "client_token_version": _token_version(getattr(client, "client_token_version", 0)),
    })
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "client": {
            "id": client.id,
            "name": client.name,
            "status": client.status,
            "organization_id": client.organization_id,
        },
    }


@router.post("/refresh")
def refresh_access_token(
    response: Response,
    request: Request,
    body: Optional[RefreshRequest] = Body(default=None),
    session: Session = Depends(get_session),
):
    enforce_request_rate_limit(
        request,
        bucket="auth-refresh",
        max_attempts=30,
        window_seconds=60,
        detail="For mange session-fornyelser. Prøv igen senere.",
    )
    refresh_token = _get_refresh_token_from_request(request, body)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Intet refresh token")

    token_hash = _hash_refresh_token(refresh_token)
    token_row = session.exec(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).first()
    if token_row is None:
        raise HTTPException(status_code=401, detail="Ugyldigt refresh token")

    if token_row.revoked_at is not None:
        _revoke_all_user_refresh_tokens(session, token_row.user_id)
        session.commit()
        raise HTTPException(status_code=401, detail="Refresh token er revokeret — log ind igen")

    now = datetime.now(timezone.utc)
    expires_at = _coerce_aware_utc(token_row.expires_at)
    session_expires_at = _refresh_session_expires_at(token_row)
    if not expires_at or expires_at < now or session_expires_at < now:
        raise HTTPException(status_code=401, detail="Sessionen er udløbet")

    user = session.get(User, token_row.user_id)
    if not user or not user.is_active:
        if user:
            _revoke_all_user_refresh_tokens(session, user.id)
            session.commit()
        raise HTTPException(status_code=401, detail="Brugeren findes ikke eller er deaktiveret")

    token_row.revoked_at = now.replace(tzinfo=None)
    session.add(token_row)
    new_refresh, new_refresh_expires_at, absolute_expiry = _create_refresh_token(
        session, user.id, request, session_expires_at=session_expires_at
    )
    access_token = create_access_token(data={
        "sub": user.username,
        "uid": user.id,
        "role": getattr(user, "role", "bruger"),
        "token_version": _token_version(getattr(user, "token_version", 0)),
    }, session_expires_at=absolute_expiry)

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Kunne ikke forny session")

    _set_auth_cookie(response, access_token)
    _set_refresh_cookie(response, new_refresh, _refresh_token_max_age_seconds(new_refresh_expires_at))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "session_expires_at": _session_expiry_iso(absolute_expiry),
        "user": _user_response(user),
    }


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    body: Optional[LogoutRequest] = Body(default=None),
    session: Session = Depends(get_session),
):
    refresh_token = body.refresh_token if body and body.refresh_token else request.cookies.get(REFRESH_COOKIE_NAME)
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="none" if IS_PRODUCTION else "lax",
        path="/",
    )
    _clear_refresh_cookie(response)

    if refresh_token:
        token_row = session.exec(select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh_token(refresh_token))).first()
        if token_row and token_row.revoked_at is None:
            token_row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(token_row)
            try:
                session.commit()
            except Exception:
                session.rollback()

    return {"ok": True}


@router.get("/me")
def get_me(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    payload = _decode_token_or_raise(token)
    user = _user_from_payload(payload, session)
    return _user_response(user)



def get_current_user_or_client(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> Union[User, Client]:
    payload = _decode_token_or_raise(token)
    if payload.get("principal") == "client":
        return _client_from_payload(payload, session)
    return _user_from_payload(payload, session)


def principal_is_client(principal) -> bool:
    return isinstance(principal, Client)


def require_client_self_or_user(principal, client_id: int):
    if isinstance(principal, Client):
        if principal.id != client_id:
            raise HTTPException(status_code=403, detail="Klient-token må kun tilgå egen klient")
        return
    if isinstance(principal, User):
        return
    raise HTTPException(status_code=403, detail="Ugyldig principal")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    payload = _decode_token_or_raise(token)
    return _user_from_payload(payload, session)


def get_current_admin_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    user = get_current_user(token=token, session=session)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Kun administratorer har adgang")
    return user


def get_current_superadmin_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    user = get_current_user(token=token, session=session)
    if not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Kun superadministratorer har adgang")
    return user




def verify_ws_token(token: str, session: Session) -> Optional[Union[User, Client]]:
    """
    Validerer JWT-token til WebSocket/stream helpers.

    Returnerer enten User eller Client. Token-versionen kontrolleres, så
    password change, deaktivering og client-secret rotation invalidierer gamle
    tokens med det samme.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            leeway=10,
            options={"require": list(JWT_REQUIRED_CLAIMS)},
        )
        if payload.get("principal") == "client":
            return _client_from_payload(payload, session)
        return _user_from_payload(payload, session)
    except Exception:
        return None
