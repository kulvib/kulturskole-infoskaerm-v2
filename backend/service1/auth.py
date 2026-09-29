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
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlmodel import Session, select

from .audit import add_audit_log, commit_audit_log
from .db import get_session
from .models import Client, Organization, RefreshToken, User
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


class ImpersonationStartRequest(BaseModel):
    target_user_id: int


class ImpersonationCandidateOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    role: str
    organization_id: Optional[int] = None
    organization_name: Optional[str] = None
    must_change_password: bool


class ActiveSessionOut(BaseModel):
    session_id: str
    current: bool
    refreshed_at: datetime
    session_expires_at: datetime
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    impersonation_active: bool = False


class SessionRevokeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SessionRevokeOthersRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class SessionRevokeResult(BaseModel):
    revoked_count: int


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


def _create_refresh_token(
    session: Session,
    user_id: int,
    request: Request,
    session_expires_at: Optional[datetime] = None,
    *,
    impersonated_user_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> tuple[str, datetime, datetime, RefreshToken]:
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
        session_id=session_id or uuid.uuid4().hex,
        impersonated_user_id=impersonated_user_id,
        created_ip=get_client_ip(request),
        user_agent=(request.headers.get("user-agent", "") or "")[:500],
    )
    session.add(row)
    return token, expires_at, absolute_expiry, row


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
    """Resolve an active browser login context without exposing a session secret.

    The binding is stable across normal refresh rotation, but it includes the
    effective-user context. Starting or stopping user switching therefore makes
    capabilities from the previous context invalid immediately.
    """
    binding = str(auth_session_binding or "").strip()
    if not binding:
        return None

    effective_user = session.get(User, int(user_id))
    if (
        effective_user is None
        or not effective_user.is_active
        or _token_version(effective_user.token_version) != _token_version(user_token_version)
    ):
        return None

    now = datetime.now(timezone.utc)
    rows = session.exec(
        select(RefreshToken).where(
            RefreshToken.revoked_at.is_(None),
            or_(
                RefreshToken.user_id == int(user_id),
                RefreshToken.impersonated_user_id == int(user_id),
            ),
        )
    ).all()
    for row in rows:
        refresh_expiry = _coerce_aware_utc(row.expires_at)
        session_expiry = _refresh_session_expires_at(row)
        if not refresh_expiry or refresh_expiry <= now or session_expiry <= now:
            continue
        session_expiry_iso = _session_expiry_iso(session_expiry)

        if row.impersonated_user_id is None:
            if row.user_id != int(user_id):
                continue
            material = (
                f"user:{int(effective_user.id)}:{_token_version(effective_user.token_version)}:"
                f"{session_expiry_iso}"
            )
        else:
            if row.impersonated_user_id != int(user_id):
                continue
            actor = session.get(User, row.user_id)
            if actor is None:
                continue
            try:
                _assert_impersonation_allowed(actor, effective_user)
            except HTTPException:
                continue
            material = (
                f"impersonation:{int(actor.id)}:{_token_version(actor.token_version)}:"
                f"{int(effective_user.id)}:{_token_version(effective_user.token_version)}:"
                f"{session_expiry_iso}"
            )

        candidate = hashlib.sha256(material.encode("utf-8")).hexdigest()
        if secrets.compare_digest(candidate, binding):
            return effective_user
    return None


def get_access_token_session_binding(token: str, user: User) -> str:
    """Return a stable, non-secret binding for the current browser user context."""
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
    if _token_version(payload.get("token_version")) != _token_version(user.token_version):
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    raw_session_expiry = str(payload.get("session_expires_at") or "").strip()
    if not raw_session_expiry:
        raise HTTPException(status_code=401, detail="Sessionen mangler sikkerhedsbinding")

    actor_uid = payload.get("actor_uid")
    if actor_uid is None:
        material = f"user:{int(user.id)}:{_token_version(user.token_version)}:{raw_session_expiry}"
    else:
        try:
            actor_id = int(actor_uid)
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Sessionen mangler administratorbinding")
        actor_token_version = _token_version(payload.get("actor_token_version"))
        if not str(payload.get("actor_sub") or "").strip():
            raise HTTPException(status_code=401, detail="Sessionen mangler administratorbinding")
        material = (
            f"impersonation:{actor_id}:{actor_token_version}:"
            f"{int(user.id)}:{_token_version(user.token_version)}:{raw_session_expiry}"
        )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def require_active_browser_auth_session_binding(
    session: Session,
    *,
    token: str,
    user: User,
) -> str:
    """Require that an access token still belongs to its active login context."""
    binding = get_access_token_session_binding(token, user)
    if user.id is None:
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    active_user = validate_browser_auth_session_binding(
        session,
        user_id=int(user.id),
        user_token_version=_token_version(user.token_version),
        auth_session_binding=binding,
    )
    if active_user is None:
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    return binding


def _require_active_refresh_row(payload: dict, session: Session) -> RefreshToken:
    session_id = str(payload.get("sid") or "").strip()
    if not session_id or len(session_id) > 64:
        raise HTTPException(status_code=401, detail="Sessionen mangler sikkerhedsbinding")
    token_row = session.exec(
        select(RefreshToken).where(
            RefreshToken.session_id == session_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).first()
    if token_row is None:
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    now = datetime.now(timezone.utc)
    refresh_expiry = _coerce_aware_utc(token_row.expires_at)
    session_expiry = _refresh_session_expires_at(token_row)
    if not refresh_expiry or refresh_expiry <= now or session_expiry <= now:
        raise HTTPException(status_code=401, detail="Sessionen er udløbet")
    raw_session_expiry = str(payload.get("session_expires_at") or "").strip()
    if not raw_session_expiry or raw_session_expiry != _session_expiry_iso(session_expiry):
        raise HTTPException(status_code=401, detail="Sessionens sikkerhedsbinding matcher ikke")
    return token_row


def _assert_impersonation_allowed(actor: User, target: User, *, allow_pending_target: bool = False) -> None:
    if not actor.is_active:
        raise HTTPException(status_code=403, detail="Administratorkontoen er deaktiveret")
    if not target.is_active:
        raise HTTPException(status_code=403, detail="Brugerkontoen er deaktiveret")
    if actor.must_change_password:
        raise HTTPException(status_code=403, detail="Skift adgangskode før du arbejder som en anden bruger")
    if target.must_change_password and not allow_pending_target:
        raise HTTPException(status_code=400, detail="Brugeren skal først gennemføre sit adgangskodeskift")
    if actor.id == target.id:
        raise HTTPException(status_code=400, detail="Du arbejder allerede som denne bruger")

    if actor.is_superadmin:
        return
    if actor.role == "admin":
        if target.role in {"superadmin", "viewer"}:
            raise HTTPException(status_code=403, detail="Administrator kan ikke arbejde som denne brugerrolle")
        if actor.organization_id is None or target.organization_id != actor.organization_id:
            raise HTTPException(status_code=403, detail="Administrator kan kun arbejde som bruger i egen organisation")
        return
    raise HTTPException(status_code=403, detail="Kun administrator eller superadministrator kan skifte bruger")


def _create_user_access_token(
    *,
    actor: User,
    effective_user: User,
    refresh_row: RefreshToken,
    session_expires_at: datetime,
) -> str:
    session_id = str(getattr(refresh_row, "session_id", "") or "").strip()
    if not session_id:
        raise RuntimeError("Refresh-session mangler session-id")
    payload = {
        "sub": effective_user.username,
        "uid": effective_user.id,
        "role": getattr(effective_user, "role", "bruger"),
        "token_version": _token_version(getattr(effective_user, "token_version", 0)),
        "sid": session_id,
    }
    if actor.id != effective_user.id:
        payload.update({
            "actor_uid": actor.id,
            "actor_sub": actor.username,
            "actor_token_version": _token_version(getattr(actor, "token_version", 0)),
        })
    return create_access_token(data=payload, session_expires_at=session_expires_at)


def _resolve_user_from_payload(payload: dict, session: Session, request: Optional[Request] = None) -> User:
    if payload.get("principal") == "client":
        raise HTTPException(status_code=403, detail="Kræver bruger-token")

    token_row = _require_active_refresh_row(payload, session)
    try:
        effective_user_id = int(payload.get("uid"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Sessionen mangler brugerbinding")
    username = str(payload.get("sub") or "").strip()
    if not username:
        raise HTTPException(status_code=401, detail="Ugyldigt bruger-token")

    raw_actor_id = payload.get("actor_uid")
    impersonation_active = raw_actor_id is not None
    actor_user_id = effective_user_id
    if impersonation_active:
        try:
            actor_user_id = int(raw_actor_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Sessionen mangler administratorbinding")
        if actor_user_id == effective_user_id:
            raise HTTPException(status_code=401, detail="Ugyldig bruger-kontekst")

    expected_impersonated_user_id = effective_user_id if impersonation_active else None
    if token_row.user_id != actor_user_id or token_row.impersonated_user_id != expected_impersonated_user_id:
        raise HTTPException(status_code=401, detail="Sessionens bruger-kontekst er ændret")

    actor = session.get(User, actor_user_id)
    effective_user = actor if not impersonation_active else session.get(User, effective_user_id)
    if actor is None or effective_user is None:
        raise HTTPException(status_code=401, detail="Sessionens bruger findes ikke længere")
    if not actor.is_active or not effective_user.is_active:
        raise HTTPException(status_code=403, detail="Inaktiv eller ukendt bruger")
    if effective_user.username != username:
        raise HTTPException(status_code=401, detail="Sessionen matcher ikke brugeren")
    if _token_version(payload.get("token_version")) != _token_version(getattr(effective_user, "token_version", 0)):
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")

    if impersonation_active:
        if str(payload.get("actor_sub") or "") != str(actor.username):
            raise HTTPException(status_code=401, detail="Sessionen matcher ikke administratoren")
        if _token_version(payload.get("actor_token_version")) != _token_version(getattr(actor, "token_version", 0)):
            raise HTTPException(status_code=401, detail="Administratorsessionen er ikke længere gyldig")
        _assert_impersonation_allowed(actor, effective_user)

    if request is not None:
        request.state.real_actor = actor
        request.state.current_user = effective_user
        request.state.impersonation_active = impersonation_active
        request.state.refresh_token_row_id = token_row.id

    return effective_user


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


def _user_response(user: User, *, actor: Optional[User] = None) -> dict:
    impersonation_active = actor is not None and actor.id != user.id
    return {
        "id": user.id,
        "username": user.username,
        "role": getattr(user, "role", "bruger"),
        "full_name": user.full_name,
        "remarks": user.remarks,
        "organization_id": user.organization_id,
        "email": user.email,
        "must_change_password": user.must_change_password,
        "impersonation_active": impersonation_active,
        "actor_user_id": actor.id if impersonation_active else None,
        "actor_username": actor.username if impersonation_active else None,
        "actor_full_name": actor.full_name if impersonation_active else None,
        "actor_role": getattr(actor, "role", None) if impersonation_active else None,
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

    refresh_token, refresh_expires_at, session_expires_at, refresh_row = _create_refresh_token(
        session, user.id, request
    )
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
        access_token = _create_user_access_token(
            actor=user,
            effective_user=user,
            refresh_row=refresh_row,
            session_expires_at=session_expires_at,
        )
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

    actor = session.get(User, token_row.user_id)
    if not actor or not actor.is_active:
        if actor:
            _revoke_all_user_refresh_tokens(session, actor.id)
            session.commit()
        raise HTTPException(status_code=401, detail="Brugeren findes ikke eller er deaktiveret")

    effective_user = actor
    if token_row.impersonated_user_id is not None:
        effective_user = session.get(User, token_row.impersonated_user_id)
        if effective_user is None:
            token_row.revoked_at = now.replace(tzinfo=None)
            session.add(token_row)
            session.commit()
            raise HTTPException(status_code=401, detail="Den valgte bruger findes ikke længere")
        _assert_impersonation_allowed(actor, effective_user)

    token_row.revoked_at = now.replace(tzinfo=None)
    session.add(token_row)
    new_refresh, new_refresh_expires_at, absolute_expiry, new_refresh_row = _create_refresh_token(
        session,
        actor.id,
        request,
        session_expires_at=session_expires_at,
        impersonated_user_id=(effective_user.id if effective_user.id != actor.id else None),
        session_id=(str(token_row.session_id).strip() if token_row.session_id else uuid.uuid4().hex),
    )

    try:
        session.flush()
        access_token = _create_user_access_token(
            actor=actor,
            effective_user=effective_user,
            refresh_row=new_refresh_row,
            session_expires_at=absolute_expiry,
        )
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
        "user": _user_response(effective_user, actor=actor),
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
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    payload = _decode_token_or_raise(token)
    user = _resolve_user_from_payload(payload, session, request=request)
    actor = getattr(request.state, "real_actor", None)
    return _user_response(user, actor=actor)


def get_current_user_or_client(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> Union[User, Client]:
    payload = _decode_token_or_raise(token)
    if payload.get("principal") == "client":
        return _client_from_payload(payload, session)
    return _resolve_user_from_payload(payload, session, request=request)


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
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    payload = _decode_token_or_raise(token)
    return _resolve_user_from_payload(payload, session, request=request)


def get_current_admin_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    user = get_current_user(request=request, token=token, session=session)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Kun administratorer har adgang")
    return user


def get_current_superadmin_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    user = get_current_user(request=request, token=token, session=session)
    if not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Kun superadministratorer har adgang")
    return user


def _current_refresh_row_for_context(request: Request, session: Session, actor: User) -> RefreshToken:
    row_id = getattr(request.state, "refresh_token_row_id", None)
    if not isinstance(row_id, int) or row_id < 1:
        raise HTTPException(status_code=401, detail="Sessionen mangler sikkerhedsbinding")
    row = session.get(RefreshToken, row_id)
    if row is None or row.revoked_at is not None or row.user_id != actor.id:
        raise HTTPException(status_code=401, detail="Sessionen er ikke længere gyldig")
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token or not secrets.compare_digest(row.token_hash, _hash_refresh_token(refresh_token)):
        raise HTTPException(status_code=409, detail="Sessionen blev fornyet. Prøv handlingen igen")
    now = datetime.now(timezone.utc)
    refresh_expiry = _coerce_aware_utc(row.expires_at)
    session_expiry = _refresh_session_expires_at(row)
    if not refresh_expiry or refresh_expiry <= now or session_expiry <= now:
        raise HTTPException(status_code=401, detail="Sessionen er udløbet")
    return row


def _session_security_actor(request: Request, current_user: User) -> User:
    actor = getattr(request.state, "real_actor", None) or current_user
    if getattr(request.state, "impersonation_active", False) or actor.id != current_user.id:
        raise HTTPException(status_code=409, detail="Afslut det aktive bruger-skift først")
    return actor


def _set_session_security_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _require_session_security_password(
    *,
    request: Request,
    session: Session,
    actor: User,
    password: str,
) -> None:
    key = f"user:{int(actor.id)}"
    assert_key_not_limited(
        bucket="session-security-password",
        key=key,
        max_attempts=5,
        window_seconds=300,
        detail="For mange mislykkede godkendelsesforsøg. Prøv igen senere.",
    )
    if not verify_password(password, actor.hashed_password):
        record_key_attempt(
            bucket="session-security-password",
            key=key,
            window_seconds=300,
        )
        commit_audit_log(
            session,
            action="session_reauthentication_failed",
            request=request,
            actor=actor,
            target_user=actor,
            entity_type="session",
            status="failed",
            severity="warning",
            details={"reason": "wrong_password"},
        )
        raise HTTPException(status_code=403, detail="Adgangskoden er forkert")
    clear_key_rate_limit(bucket="session-security-password", key=key)


def _active_session_rows(session: Session, actor: User) -> list[RefreshToken]:
    now = datetime.now(timezone.utc)
    rows = session.exec(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == int(actor.id),
            RefreshToken.revoked_at.is_(None),
        )
        .order_by(RefreshToken.created_at.desc(), RefreshToken.id.desc())
    ).all()
    active: list[RefreshToken] = []
    for row in rows:
        refresh_expiry = _coerce_aware_utc(row.expires_at)
        session_expiry = _refresh_session_expires_at(row)
        if not refresh_expiry or refresh_expiry <= now or session_expiry <= now:
            continue
        session_id = str(row.session_id or "").strip()
        if not session_id:
            continue
        active.append(row)
    return active


@router.get("/sessions", response_model=list[ActiveSessionOut])
def list_active_sessions(
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    actor = _session_security_actor(request, current_user)
    _set_session_security_no_store(response)
    current_row = _current_refresh_row_for_context(request, session, actor)
    current_session_id = str(current_row.session_id or "").strip()
    if not current_session_id:
        raise HTTPException(status_code=401, detail="Sessionen mangler sikkerhedsbinding")

    result: list[ActiveSessionOut] = []
    seen: set[str] = set()
    for row in _active_session_rows(session, actor):
        session_id = str(row.session_id or "").strip()
        if session_id in seen:
            continue
        seen.add(session_id)
        refreshed_at = _coerce_aware_utc(row.created_at) or datetime.now(timezone.utc)
        result.append(
            ActiveSessionOut(
                session_id=session_id,
                current=session_id == current_session_id,
                refreshed_at=refreshed_at,
                session_expires_at=_refresh_session_expires_at(row),
                user_agent=(str(row.user_agent).strip() if row.user_agent else None),
                ip_address=(str(row.created_ip).strip() if row.created_ip else None),
                impersonation_active=row.impersonated_user_id is not None,
            )
        )

    if sum(1 for row in result if row.current) != 1:
        raise HTTPException(status_code=401, detail="Den aktuelle session kunne ikke identificeres sikkert")
    result.sort(key=lambda row: (not row.current, -row.refreshed_at.timestamp()))
    return result


@router.post("/sessions/revoke", response_model=SessionRevokeResult)
def revoke_active_session(
    payload: SessionRevokeRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    actor = _session_security_actor(request, current_user)
    _set_session_security_no_store(response)
    current_row = _current_refresh_row_for_context(request, session, actor)
    current_session_id = str(current_row.session_id or "").strip()
    target_session_id = payload.session_id.strip()
    if not current_session_id:
        raise HTTPException(status_code=401, detail="Sessionen mangler sikkerhedsbinding")
    if target_session_id == current_session_id:
        raise HTTPException(status_code=400, detail="Brug Log ud for at afslutte den aktuelle session")

    _require_session_security_password(
        request=request,
        session=session,
        actor=actor,
        password=payload.password,
    )

    rows = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == int(actor.id),
            RefreshToken.session_id == target_session_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all()
    now_aware = datetime.now(timezone.utc)
    now = now_aware.replace(tzinfo=None)
    active_rows = [
        row
        for row in rows
        if (_coerce_aware_utc(row.expires_at) or datetime.min.replace(tzinfo=timezone.utc)) > now_aware
        and _refresh_session_expires_at(row) > now_aware
    ]
    if not active_rows:
        raise HTTPException(status_code=404, detail="Sessionen findes ikke eller er allerede afsluttet")

    for row in active_rows:
        row.revoked_at = now
        session.add(row)
    add_audit_log(
        session,
        action="session_revoked",
        request=request,
        actor=actor,
        target_user=actor,
        entity_type="session",
        entity_label="remote-session",
        severity="warning",
        details={
            "revoked_count": len(active_rows),
            "target_impersonation_active": any(row.impersonated_user_id is not None for row in active_rows),
        },
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Kunne ikke afslutte sessionen")
    return SessionRevokeResult(revoked_count=len(active_rows))


@router.post("/sessions/revoke-others", response_model=SessionRevokeResult)
def revoke_other_sessions(
    payload: SessionRevokeOthersRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    actor = _session_security_actor(request, current_user)
    _set_session_security_no_store(response)
    current_row = _current_refresh_row_for_context(request, session, actor)
    current_session_id = str(current_row.session_id or "").strip()
    if not current_session_id:
        raise HTTPException(status_code=401, detail="Sessionen mangler sikkerhedsbinding")

    _require_session_security_password(
        request=request,
        session=session,
        actor=actor,
        password=payload.password,
    )

    now_aware = datetime.now(timezone.utc)
    now = now_aware.replace(tzinfo=None)
    rows = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == int(actor.id),
            RefreshToken.revoked_at.is_(None),
            or_(
                RefreshToken.session_id != current_session_id,
                RefreshToken.session_id.is_(None),
            ),
        )
    ).all()
    active_rows = [
        row
        for row in rows
        if (_coerce_aware_utc(row.expires_at) or datetime.min.replace(tzinfo=timezone.utc)) > now_aware
        and _refresh_session_expires_at(row) > now_aware
    ]
    for row in active_rows:
        row.revoked_at = now
        session.add(row)
    add_audit_log(
        session,
        action="other_sessions_revoked",
        request=request,
        actor=actor,
        target_user=actor,
        entity_type="session",
        entity_label="other-sessions",
        severity="warning",
        details={"revoked_count": len(active_rows)},
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Kunne ikke afslutte andre sessioner")
    return SessionRevokeResult(revoked_count=len(active_rows))


def _candidate_out(user: User, organization_names: dict[int, str]) -> ImpersonationCandidateOut:
    return ImpersonationCandidateOut(
        id=int(user.id),
        username=user.username,
        full_name=user.full_name,
        role=getattr(user, "role", "bruger"),
        organization_id=user.organization_id,
        organization_name=organization_names.get(int(user.organization_id)) if user.organization_id is not None else None,
        must_change_password=bool(user.must_change_password),
    )


@router.get("/impersonation/candidates", response_model=list[ImpersonationCandidateOut])
def list_impersonation_candidates(
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    actor = getattr(request.state, "real_actor", None) or current_user
    if getattr(request.state, "impersonation_active", False):
        raise HTTPException(status_code=409, detail="Afslut det aktive bruger-skift først")
    if not (actor.is_superadmin or actor.role == "admin"):
        raise HTTPException(status_code=403, detail="Kun administrator eller superadministrator kan skifte bruger")

    statement = select(User).where(User.id != actor.id, User.is_active == True)
    if actor.role == "admin" and not actor.is_superadmin:
        if actor.organization_id is None:
            return []
        statement = statement.where(
            User.organization_id == actor.organization_id,
            User.role.in_(["admin", "bruger"]),
        )
    rows = session.exec(statement.order_by(User.full_name, User.username, User.id)).all()

    candidates: list[User] = []
    for user in rows:
        try:
            _assert_impersonation_allowed(actor, user, allow_pending_target=True)
        except HTTPException:
            continue
        candidates.append(user)

    org_ids = sorted({int(user.organization_id) for user in candidates if user.organization_id is not None})
    organization_names: dict[int, str] = {}
    if org_ids:
        organizations = session.exec(select(Organization).where(Organization.id.in_(org_ids))).all()
        organization_names = {int(org.id): org.name for org in organizations if org.id is not None}
    return [_candidate_out(user, organization_names) for user in candidates]


@router.post("/impersonation/start")
def start_impersonation(
    payload: ImpersonationStartRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    enforce_request_rate_limit(
        request,
        bucket="impersonation-start",
        max_attempts=5,
        window_seconds=60,
        detail="For mange bruger-skift. Prøv igen senere.",
    )
    actor = getattr(request.state, "real_actor", None) or current_user
    if getattr(request.state, "impersonation_active", False):
        raise HTTPException(status_code=409, detail="Du arbejder allerede som en anden bruger")
    target = session.get(User, payload.target_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Brugeren blev ikke fundet")
    _assert_impersonation_allowed(actor, target)

    current_row = _current_refresh_row_for_context(request, session, actor)
    if current_row.impersonated_user_id is not None:
        raise HTTPException(status_code=409, detail="Sessionen er allerede i bruger-skift")
    session_expires_at = _refresh_session_expires_at(current_row)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_row.revoked_at = now
    session.add(current_row)
    refresh_token, refresh_expires_at, absolute_expiry, new_row = _create_refresh_token(
        session,
        int(actor.id),
        request,
        session_expires_at=session_expires_at,
        impersonated_user_id=int(target.id),
    )
    add_audit_log(
        session,
        action="impersonation_started",
        request=request,
        actor=actor,
        target_user=target,
        entity_type="session",
        entity_id=int(target.id),
        entity_label=target.username,
        severity="critical",
        is_critical=True,
        details={
            "effective_user_id": target.id,
            "effective_username": target.username,
            "effective_role": target.role,
            "effective_organization_id": target.organization_id,
        },
    )
    try:
        session.flush()
        access_token = _create_user_access_token(
            actor=actor,
            effective_user=target,
            refresh_row=new_row,
            session_expires_at=absolute_expiry,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Kunne ikke skifte bruger")

    _set_auth_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token, _refresh_token_max_age_seconds(refresh_expires_at))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "session_expires_at": _session_expiry_iso(absolute_expiry),
        "user": _user_response(target, actor=actor),
    }


@router.post("/impersonation/stop")
def stop_impersonation(
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    actor = getattr(request.state, "real_actor", None) or current_user
    if not getattr(request.state, "impersonation_active", False) or actor.id == current_user.id:
        raise HTTPException(status_code=409, detail="Du arbejder ikke som en anden bruger")

    current_row = _current_refresh_row_for_context(request, session, actor)
    if current_row.impersonated_user_id != current_user.id:
        raise HTTPException(status_code=409, detail="Sessionens bruger-kontekst er ændret")
    session_expires_at = _refresh_session_expires_at(current_row)
    current_row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(current_row)
    refresh_token, refresh_expires_at, absolute_expiry, new_row = _create_refresh_token(
        session,
        int(actor.id),
        request,
        session_expires_at=session_expires_at,
    )
    add_audit_log(
        session,
        action="impersonation_stopped",
        request=request,
        actor=actor,
        target_user=current_user,
        entity_type="session",
        entity_id=int(current_user.id),
        entity_label=current_user.username,
        severity="critical",
        is_critical=True,
        details={
            "effective_user_id": current_user.id,
            "effective_username": current_user.username,
            "effective_role": current_user.role,
            "effective_organization_id": current_user.organization_id,
        },
    )
    try:
        session.flush()
        access_token = _create_user_access_token(
            actor=actor,
            effective_user=actor,
            refresh_row=new_row,
            session_expires_at=absolute_expiry,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Kunne ikke afslutte bruger-skift")

    _set_auth_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token, _refresh_token_max_age_seconds(refresh_expires_at))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "session_expires_at": _session_expiry_iso(absolute_expiry),
        "user": _user_response(actor),
    }


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
        return _resolve_user_from_payload(payload, session)
    except Exception:
        return None
