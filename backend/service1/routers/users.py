import hashlib
import html
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator
from sqlalchemy import delete, func, or_, update
from sqlmodel import Session, select

from ..audit import AUDIT_LOG_RETENTION_DAYS, add_audit_log, commit_audit_log
from ..auth import (
    get_current_admin_user,
    get_current_user,
    get_password_hash,
    validate_password_strength,
    verify_password,
    _revoke_all_user_refresh_tokens,
)
from ..branding import MAIL_LOGO_URL, MAIL_PRODUCT_NAME, PRODUCT_DOMAIN
from ..db import get_session
from ..email_service import send_email
from ..models import AuditLog, EnrollmentToken, OrganizationLogo, RefreshToken, User
from ..observability import log_safe_exception
from ..rate_limit import enforce_request_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()

ROLLE_VISNING = {
    "superadmin": "Superadministrator",
    "admin": "Administrator",
    "bruger": "Bruger",
    "viewer": "Se adgang",
}

# Roller som en normal admin (ikke superadmin) må tildele
ADMIN_ALLOWED_ROLES = ["admin", "bruger"]
ROLES_REQUIRING_ORGANIZATION = {"admin", "bruger", "viewer"}
ROLES_WITHOUT_ORGANIZATION = {"superadmin"}
PASSWORD_RESET_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_EXPIRE_MINUTES", "30"))
PASSWORD_RESET_REQUEST_MESSAGE = "Hvis kontoen findes, sender vi en mail med et link til nulstilling af adgangskoden."
EMAIL_BUTTON_STYLE = (
    "display:inline-block;background:#14b8a6;color:#ffffff;"
    "padding:10px 16px;border-radius:8px;text-decoration:none;font-weight:700;"
)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _count_active_superadmins(session: Session) -> int:
    return len(
        session.exec(
            select(User).where(User.role == "superadmin", User.is_active == True)
        ).all()
    )


def _require_role_assignment_allowed(current_user: User, requested_role: str):
    """Kontrollér at current_user må tildele requested_role."""
    if current_user.is_superadmin:
        return  # superadministrator må alt
    if requested_role == "superadmin":
        raise HTTPException(
            status_code=403,
            detail="Kun superadministratorer må oprette eller tildele rollen Superadministrator",
        )
    if requested_role == "viewer":
        raise HTTPException(
            status_code=403,
            detail="Kun superadministratorer må oprette eller tildele rollen Se adgang",
        )
    if requested_role not in ADMIN_ALLOWED_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Du har ikke adgang til at tildele denne rolle",
        )


def _require_can_manage_target(current_user: User, target_user: User):
    """Kontrollér at current_user må redigere/deaktivere target_user."""
    if current_user.is_superadmin:
        return  # superadministrator må alt
    if target_user.role == "superadmin":
        raise HTTPException(
            status_code=403,
            detail="Kun superadministratorer må administrere superadministratorer",
        )
    if target_user.role == "viewer":
        raise HTTPException(
            status_code=403,
            detail="Kun superadministratorer må administrere Se adgang-brugere",
        )
    if current_user.is_admin and target_user.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=403,
            detail="Du kan kun administrere brugere i din egen organisation",
        )


def _normalize_role_organization(role: str, organization_id: Optional[int]) -> Optional[int]:
    """Håndhæver organisation-reglen for roller.

    superadmin må ikke være tilknyttet organisation.
    admin/bruger/viewer skal være tilknyttet organisation.
    """
    if role in ROLES_WITHOUT_ORGANIZATION:
        return None
    if role in ROLES_REQUIRING_ORGANIZATION and organization_id is None:
        raise HTTPException(
            status_code=400,
            detail="Administrator-, bruger- og viewer-roller skal tilknyttes en organisation",
        )
    return organization_id


def _require_admin_has_organization(current_user: User) -> None:
    """En normal admin skal selv have organisation for at administrere andre brugere."""
    if not current_user.is_superadmin and current_user.is_admin and current_user.organization_id is None:
        raise HTTPException(
            status_code=403,
            detail="Administrator mangler organisation og kan ikke administrere brugere",
        )


def _normalize_identifier(value: str) -> str:
    return (value or "").strip().lower()


def _find_user_by_username_or_email(session: Session, identifier: str) -> Optional[User]:
    normalized = _normalize_identifier(identifier)
    if not normalized:
        return None
    return session.exec(
        select(User).where(
            or_(
                func.lower(User.username) == normalized,
                func.lower(User.email) == normalized,
            )
        )
    ).first()


def _user_identifier_exists(session: Session, username: str, email: str, exclude_user_id: Optional[int] = None) -> bool:
    stmt = select(User).where(
        or_(
            func.lower(User.username) == username.strip().lower(),
            func.lower(User.email) == email.strip().lower(),
        )
    )
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return session.exec(stmt).first() is not None


def _role_label(role: Optional[str]) -> Optional[str]:
    return {
        "superadmin": "superadministrator",
        "admin": "administrator",
        "viewer": "viewer",
        "bruger": "bruger",
    }.get(role or "", role)


def _changed_fields(before: dict, after: dict) -> list[str]:
    return [key for key, old_value in before.items() if old_value != after.get(key)]


def _iso(value):
    return value.isoformat() if value else None


def _generate_internal_temporary_password() -> str:
    return f"{secrets.token_urlsafe(36)}Aa1"


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_frontend_base_url() -> str:
    candidates = [
        os.getenv("PASSWORD_RESET_FRONTEND_URL"),
        os.getenv("FRONTEND_URL"),
        (os.getenv("CORS_ALLOW_ORIGINS") or "").split(",")[0],
        f"https://{PRODUCT_DOMAIN}",
    ]
    for candidate in candidates:
        value = (candidate or "").strip().rstrip("/")
        if value:
            return value
    return f"https://{PRODUCT_DOMAIN}"


def _build_password_reset_link(token: str) -> str:
    return f"{_get_frontend_base_url()}/nulstil-adgangskode?token={token}"


def _email_plain_signature() -> str:
    return f"Med venlig hilsen\n{MAIL_PRODUCT_NAME}\n{PRODUCT_DOMAIN}"


def _email_html_signature() -> str:
    safe_service_name = html.escape(MAIL_PRODUCT_NAME)
    safe_service_domain = html.escape(PRODUCT_DOMAIN)
    safe_logo_url = html.escape(MAIL_LOGO_URL, quote=True)
    return (
        f'<div style="margin-top:24px;color:#475569;">'
        f'<p style="margin:0 0 12px 0;">'
        f'Med venlig hilsen<br>'
        f'<strong>{safe_service_name}</strong><br>'
        f'{safe_service_domain}'
        f'</p>'
        f'<img src="{safe_logo_url}" alt="{safe_service_name}" width="260" '
        f'style="display:block;width:260px;max-width:100%;height:auto;border:0;outline:none;text-decoration:none;">'
        f'</div>'
    )


def _password_reset_email_content(db_user: User, reset_link: str, purpose: str) -> tuple[str, str, str]:
    """Returnér subject, text og HTML for aktiverings-/resetmail."""
    plain_name = db_user.full_name or db_user.username
    display_name = html.escape(plain_name or "")
    escaped_link = html.escape(reset_link, quote=True)
    safe_service_name = html.escape(MAIL_PRODUCT_NAME)
    safe_service_domain = html.escape(PRODUCT_DOMAIN)
    expire_minutes = PASSWORD_RESET_EXPIRE_MINUTES

    if purpose == "activation":
        subject = f"Velkommen til {MAIL_PRODUCT_NAME}"
        intro_text = f"Du er oprettet som bruger i {MAIL_PRODUCT_NAME}."
        action_text = "Åbn dette link for at vælge din adgangskode:"
        ignore_text = "Hvis du ikke forventede denne mail, kan du ignorere den."
        link_text = "Vælg adgangskode"
    elif purpose == "admin_reset":
        subject = f"Vælg ny adgangskode til {MAIL_PRODUCT_NAME}"
        intro_text = f"En administrator har sendt dig et link til at vælge en ny adgangskode til {MAIL_PRODUCT_NAME}."
        action_text = "Åbn dette link for at vælge en ny adgangskode:"
        ignore_text = "Hvis du ikke forventede denne mail, kan du kontakte din administrator."
        link_text = "Vælg ny adgangskode"
    else:
        subject = f"Nulstil adgangskode til {MAIL_PRODUCT_NAME}"
        intro_text = f"Du har bedt om at nulstille adgangskoden til {MAIL_PRODUCT_NAME}."
        action_text = "Åbn dette link for at vælge en ny adgangskode:"
        ignore_text = "Hvis du ikke selv har bedt om dette, kan du ignorere denne mail."
        link_text = "Vælg ny adgangskode"

    text_body = (
        f"Hej {plain_name}\n\n"
        f"{intro_text}\n\n"
        f"{action_text}\n{reset_link}\n\n"
        f"Linket udløber om {expire_minutes} minutter.\n\n"
        f"{ignore_text}\n\n"
        f"{_email_plain_signature()}"
    )

    html_body = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.55;color:#0f172a;max-width:640px;">
      <p>Hej {display_name}</p>
      <p>{html.escape(intro_text)}</p>
      <p>{html.escape(action_text)}</p>
      <p style="margin:18px 0;">
        <a href="{escaped_link}" style="{EMAIL_BUTTON_STYLE}">{html.escape(link_text)}</a>
      </p>
      <p style="font-size:13px;color:#64748b;">
        Linket udløber om {expire_minutes} minutter. Du kan også kopiere dette link ind i browseren:<br>
        <span style="word-break:break-all;">{escaped_link}</span>
      </p>
      <p>{html.escape(ignore_text)}</p>
      <p style="font-size:13px;color:#64748b;">
        Denne mail er sendt fra {safe_service_name} på {safe_service_domain}.
      </p>
      {_email_html_signature()}
    </div>
    """
    return subject, text_body, html_body


def _password_changed_email_content(db_user: User) -> tuple[str, str, str]:
    """Returnér subject, text og HTML til sikkerhedsnotifikation efter passwordskift.

    Mailen har bevidst ingen knap, fordi adgangskoden allerede er ændret.
    """
    plain_name = db_user.full_name or db_user.username
    display_name = html.escape(plain_name or "")
    safe_service_name = html.escape(MAIL_PRODUCT_NAME)
    safe_service_domain = html.escape(PRODUCT_DOMAIN)
    subject = f"Adgangskode ændret til {MAIL_PRODUCT_NAME}"

    text_body = (
        f"Hej {plain_name}\n\n"
        f"Din adgangskode til {MAIL_PRODUCT_NAME} er blevet ændret.\n"
        f"Denne mail vedrører {MAIL_PRODUCT_NAME} på {PRODUCT_DOMAIN}.\n\n"
        f"Hvis det var dig, behøver du ikke gøre mere.\n"
        f"Hvis du ikke selv har ændret adgangskoden, skal du kontakte din administrator med det samme.\n\n"
        f"Denne mail er sendt automatisk og kan ikke besvares.\n\n"
        f"{_email_plain_signature()}"
    )
    html_body = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.55;color:#0f172a;max-width:640px;">
      <p>Hej {display_name}</p>
      <p>Din adgangskode til <strong>{safe_service_name}</strong> er blevet ændret.</p>
      <p>Denne mail vedrører <strong>{safe_service_name}</strong> på {safe_service_domain}.</p>
      <p>Hvis det var dig, behøver du ikke gøre mere.</p>
      <p>Hvis du ikke selv har ændret adgangskoden, skal du kontakte din administrator med det samme.</p>
      <p style="color:#64748b;font-size:13px;">Denne mail er sendt automatisk og kan ikke besvares.</p>
      {_email_html_signature()}
    </div>
    """
    return subject, text_body, html_body


async def _send_password_changed_notification(
    *,
    db_user: User,
    request: Request,
) -> None:
    """Send sikkerhedsnotifikation efter passwordskift. Fejl må ikke blokere brugerflowet."""
    if not getattr(db_user, "email", None):
        return

    try:
        subject, text_body, html_body = _password_changed_email_content(db_user)
        await send_email(
            to=db_user.email,
            subject=subject,
            text=text_body,
            html=html_body,
        )
        logger.info("password_change_notification_sent user_id=%s", db_user.id)
    except Exception as exc:
        log_safe_exception(
            logger,
            exc,
            event="password_change_notification_failed",
            user_id=getattr(db_user, "id", None),
        )


async def _send_password_reset_link(
    session: Session,
    db_user: User,
    request: Request,
    *,
    purpose: str = "forgot",
    lockout_existing_password: bool = False,
) -> None:
    if not db_user.email:
        raise HTTPException(status_code=400, detail="Brugeren mangler emailadresse")
    if not db_user.is_active:
        raise HTTPException(status_code=400, detail="Brugeren er inaktiv")

    token = secrets.token_urlsafe(48)
    token_hash = _hash_reset_token(token)
    expires_at = _utcnow_naive() + timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES)
    reset_link = _build_password_reset_link(token)

    previous_security_state = {
        "hashed_password": db_user.hashed_password,
        "token_version": int(getattr(db_user, "token_version", 0) or 0),
        "must_change_password": db_user.must_change_password,
        "password_reset_token_hash": getattr(db_user, "password_reset_token_hash", None),
        "password_reset_expires_at": getattr(db_user, "password_reset_expires_at", None),
    }

    if lockout_existing_password:
        db_user.hashed_password = get_password_hash(_generate_internal_temporary_password())
        db_user.must_change_password = True
        db_user.token_version = previous_security_state["token_version"] + 1
        _revoke_all_user_refresh_tokens(session, db_user.id)

    db_user.password_reset_token_hash = token_hash
    db_user.password_reset_expires_at = expires_at

    try:
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    except Exception as exc:
        session.rollback()
        log_safe_exception(logger, exc, event="password_reset_token_save_failed", user_id=db_user.id)
        raise HTTPException(status_code=500, detail="Kunne ikke oprette nulstillingslink")

    subject, text_body, html_body = _password_reset_email_content(db_user, reset_link, purpose)
    try:
        await send_email(to=db_user.email, subject=subject, text=text_body, html=html_body)
    except Exception:
        try:
            db_user.hashed_password = previous_security_state["hashed_password"]
            db_user.token_version = previous_security_state["token_version"]
            db_user.must_change_password = previous_security_state["must_change_password"]
            db_user.password_reset_token_hash = previous_security_state["password_reset_token_hash"]
            db_user.password_reset_expires_at = previous_security_state["password_reset_expires_at"]
            session.add(db_user)
            session.commit()
        except Exception as rollback_exc:
            session.rollback()
            log_safe_exception(
                logger,
                rollback_exc,
                event="password_reset_state_rollback_failed",
                user_id=db_user.id,
            )
        raise

    logger.info(
        "password_reset_email_sent user_id=%s purpose=%s expires_at=%s",
        db_user.id,
        purpose,
        expires_at,
    )


class UserCreate(BaseModel):
    username: str
    name: Optional[str] = None
    role: str = "bruger"
    is_active: bool = True
    organization_id: Optional[int] = None
    full_name: Optional[str] = None
    remarks: Optional[str] = None
    email: str

    @field_validator("username")
    @classmethod
    def username_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Brugernavn må ikke være tomt")
        if len(v.strip()) < 3:
            raise ValueError("Brugernavn skal være mindst 3 tegn")
        return v.strip()

    @field_validator("email")
    @classmethod
    def email_basic_check(cls, v):
        if not v or "@" not in v:
            raise ValueError("Ugyldig e-mailadresse")
        return v.strip().lower()

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v):
        allowed = set(ROLLE_VISNING.keys())
        if v not in allowed:
            raise ValueError(f"Rolle skal være én af: {', '.join(sorted(allowed))}")
        return v


class UserUpdate(BaseModel):
    old_password: Optional[str] = None
    current_password: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    must_change_password: Optional[bool] = None
    organization_id: Optional[int] = None
    full_name: Optional[str] = None
    remarks: Optional[str] = None
    email: Optional[str] = None

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v):
        if v is None:
            return v
        allowed = set(ROLLE_VISNING.keys())
        if v not in allowed:
            raise ValueError(f"Rolle skal være én af: {', '.join(sorted(allowed))}")
        return v

    @field_validator("email")
    @classmethod
    def email_basic_check(cls, v):
        if v is None:
            return v
        if "@" not in v:
            raise ValueError("Ugyldig e-mailadresse")
        return v.strip().lower()


class ForgotPasswordRequest(BaseModel):
    identifier: str


class PasswordResetConfirm(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def password_must_be_strong(cls, v):
        validate_password_strength(v)
        return v


class AssignTemporaryPasswordRequest(BaseModel):
    temporary_password: str

    @field_validator("temporary_password")
    @classmethod
    def temporary_password_must_be_strong(cls, v):
        validate_password_strength(v)
        return v


class PermanentDeleteUserRequest(BaseModel):
    confirmation_email: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: datetime
    role: str
    is_active: bool
    must_change_password: bool
    organization_id: Optional[int] = None
    full_name: Optional[str] = None
    name: Optional[str] = None
    email: str
    remarks: Optional[str] = None
    last_login_at: Optional[datetime] = None
    last_login_ip: Optional[str] = None


def _serialize_utc_datetime(value: Optional[datetime]) -> Optional[str]:
    """Serialisér database-tidspunkter som entydig UTC med Z-suffiks.

    PostgreSQL-modellen gemmer UTC som naive datetimes. Uden Z tolker browseren
    værdien som lokal tid og viser audit-events to timer forkert om sommeren.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _set_no_store_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    action: str
    status: str
    actor_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    actor_role: Optional[str] = None
    actor_organization_id: Optional[int] = None
    target_user_id: Optional[int] = None
    target_username: Optional[str] = None
    target_organization_id: Optional[int] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    entity_label: Optional[str] = None
    request_id: Optional[str] = None
    request_ip: Optional[str] = None
    user_agent: Optional[str] = None
    severity: str = "info"
    is_critical: bool = False
    retention_days: Optional[int] = None
    retain_until: Optional[datetime] = None
    details: Optional[dict] = None

    @field_serializer("created_at", "retain_until", when_used="json")
    def serialize_audit_datetimes(self, value: Optional[datetime]) -> Optional[str]:
        return _serialize_utc_datetime(value)


class AuditLogRetentionOut(BaseModel):
    retention_days: int
    expired_count: int
    now: datetime

    @field_serializer("now", when_used="json")
    def serialize_now(self, value: datetime) -> str:
        return _serialize_utc_datetime(value) or ""


class AuditLogCleanupOut(BaseModel):
    retention_days: int
    deleted_count: int
    now: datetime

    @field_serializer("now", when_used="json")
    def serialize_now(self, value: datetime) -> str:
        return _serialize_utc_datetime(value) or ""


@router.get("/superadmin/audit-logs", response_model=List[AuditLogOut])
def list_audit_logs(
    response: Response,
    limit: int = 100,
    offset: int = 0,
    action: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    severity: Optional[str] = None,
    is_critical: Optional[bool] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not (current_user.is_superadmin or current_user.role == "viewer"):
        raise HTTPException(status_code=403, detail="Kun superadministrator og Se adgang må se audit-log")

    _set_no_store_headers(response)

    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))

    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if target_user_id is not None:
        stmt = stmt.where(AuditLog.target_user_id == target_user_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if severity:
        stmt = stmt.where(AuditLog.severity == severity)
    if is_critical is not None:
        stmt = stmt.where(AuditLog.is_critical == is_critical)

    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit)
    return session.exec(stmt).all()


@router.get("/superadmin/audit-logs/retention", response_model=AuditLogRetentionOut)
def get_audit_log_retention_status(
    response: Response,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not (current_user.is_superadmin or current_user.role == "viewer"):
        raise HTTPException(status_code=403, detail="Kun superadministrator og Se adgang må se audit-log")

    _set_no_store_headers(response)

    now_utc = _utcnow_naive()
    expired_count = session.exec(
        select(func.count(AuditLog.id)).where(
            AuditLog.retain_until.is_not(None),
            AuditLog.retain_until < now_utc,
        )
    ).one()
    return AuditLogRetentionOut(
        retention_days=AUDIT_LOG_RETENTION_DAYS,
        expired_count=int(expired_count or 0),
        now=now_utc,
    )


@router.post("/superadmin/audit-logs/cleanup-expired", response_model=AuditLogCleanupOut)
def cleanup_expired_audit_logs(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _set_no_store_headers(response)
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Kun superadministrator må rydde audit-log")

    now_utc = _utcnow_naive()
    expired_count = session.exec(
        select(func.count(AuditLog.id)).where(
            AuditLog.retain_until.is_not(None),
            AuditLog.retain_until < now_utc,
        )
    ).one()

    if int(expired_count or 0) > 0:
        session.execute(
            delete(AuditLog).where(
                AuditLog.retain_until.is_not(None),
                AuditLog.retain_until < now_utc,
            )
        )

    add_audit_log(
        session,
        action="audit_logs_cleanup_expired",
        request=request,
        actor=current_user,
        entity_type="audit_log",
        status="success",
        severity="warning",
        is_critical=False,
        details={
            "deleted_count": int(expired_count or 0),
            "retention_days": AUDIT_LOG_RETENTION_DAYS,
            "cutoff": now_utc.isoformat(),
        },
    )
    session.commit()

    return AuditLogCleanupOut(
        retention_days=AUDIT_LOG_RETENTION_DAYS,
        deleted_count=int(expired_count or 0),
        now=now_utc,
    )


@router.post("/users/forgot-password", response_model=dict)
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    session: Session = Depends(get_session),
):
    enforce_request_rate_limit(
        request,
        bucket="password-reset-public",
        max_attempts=5,
        window_seconds=60,
        detail="For mange nulstillingsforsøg. Prøv igen senere.",
    )

    db_user = _find_user_by_username_or_email(session, payload.identifier)
    if not db_user or not db_user.is_active:
        logger.info("password_reset_request_no_email user_found=false")
        return {"detail": PASSWORD_RESET_REQUEST_MESSAGE}

    try:
        await _send_password_reset_link(
            session,
            db_user,
            request,
            purpose="forgot",
            lockout_existing_password=False,
        )
        add_audit_log(
            session,
            action="password_reset_link_requested",
            request=request,
            target_user=db_user,
            entity_type="user",
            entity_id=db_user.id,
            entity_label=db_user.username,
            details={"source": "forgot_password"},
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        log_safe_exception(
            logger,
            exc,
            event="password_reset_request_failed",
            user_id=db_user.id,
        )

    return {"detail": PASSWORD_RESET_REQUEST_MESSAGE}


@router.post("/users/reset-password", response_model=dict)
async def reset_password_with_token(
    request: Request,
    payload: PasswordResetConfirm,
    session: Session = Depends(get_session),
):
    token = (payload.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Nulstillingstoken mangler")

    token_hash = _hash_reset_token(token)
    db_user = session.exec(select(User).where(User.password_reset_token_hash == token_hash)).first()

    expires_at = getattr(db_user, "password_reset_expires_at", None) if db_user else None
    now = _utcnow_naive()
    if not db_user or not expires_at or expires_at < now:
        if db_user:
            db_user.password_reset_token_hash = None
            db_user.password_reset_expires_at = None
            session.add(db_user)
            session.commit()
        raise HTTPException(status_code=400, detail="Nulstillingslinket er ugyldigt eller udløbet")

    if not db_user.is_active:
        raise HTTPException(status_code=400, detail="Kontoen er inaktiv. Kontakt administrator.")

    if verify_password(payload.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Ny adgangskode må ikke være den samme som den gamle")

    db_user.hashed_password = get_password_hash(payload.password)
    db_user.must_change_password = False
    db_user.token_version = int(getattr(db_user, "token_version", 0) or 0) + 1
    _revoke_all_user_refresh_tokens(session, db_user.id)
    db_user.password_reset_token_hash = None
    db_user.password_reset_expires_at = None

    add_audit_log(
        session,
        action="password_reset_completed",
        request=request,
        actor=db_user,
        target_user=db_user,
        entity_type="user",
        entity_id=db_user.id,
        entity_label=db_user.username,
        details={"source": "reset_link", "active_sessions_invalidated": True},
    )

    try:
        session.add(db_user)
        session.commit()
    except Exception as exc:
        session.rollback()
        log_safe_exception(logger, exc, event="password_reset_commit_failed", user_id=db_user.id)
        raise HTTPException(status_code=500, detail="Kunne ikke nulstille adgangskode")

    logger.info("password_reset_completed user_id=%s", db_user.id)
    await _send_password_changed_notification(db_user=db_user, request=request)
    return {"detail": "Adgangskoden er ændret"}


@router.get("/users/", response_model=List[UserRead])
def list_users(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_user),
):
    if admin.is_superadmin or admin.role == "viewer":
        return session.exec(select(User)).all()
    if admin.is_admin:
        # Administrator må kun se brugere i egen organisation, og må slet ikke se
        # Se adgang-brugere. Rollen 'viewer' er den tekniske værdi for
        # global demo-/læseadgang, som kun superadministrator må oprette,
        # se og administrere i brugeradministrationen.
        return session.exec(
            select(User).where(
                User.organization_id == admin.organization_id,
                User.role != "viewer",
            )
        ).all()
    raise HTTPException(status_code=403, detail="Du har ikke adgang til brugeradministration")


@router.post("/users/", response_model=UserRead, status_code=201)
async def create_user(
    request: Request,
    user: UserCreate,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin_user),
):
    _require_role_assignment_allowed(admin, user.role)
    _require_admin_has_organization(admin)

    if not admin.is_superadmin:
        if user.role == "superadmin":
            raise HTTPException(status_code=403, detail="Kun superadministratorer må oprette superadministratorer")
        if user.role == "viewer":
            raise HTTPException(status_code=403, detail="Kun superadministratorer må oprette Se adgang-brugere")
        user.organization_id = admin.organization_id

    user.username = user.username.strip()
    user.email = user.email.strip().lower()
    if user.full_name is None and user.name is not None:
        user.full_name = user.name
    user.organization_id = _normalize_role_organization(user.role, user.organization_id)

    if _user_identifier_exists(session, user.username, user.email):
        raise HTTPException(status_code=400, detail="Brugernavn eller email er allerede i brug")

    user_obj = User(
        username=user.username,
        hashed_password=get_password_hash(_generate_internal_temporary_password()),
        role=user.role,
        is_active=user.is_active,
        must_change_password=True,
        organization_id=user.organization_id,
        full_name=user.full_name,
        remarks=user.remarks,
        email=user.email,
    )
    try:
        session.add(user_obj)
        session.commit()
        session.refresh(user_obj)
    except Exception as exc:
        session.rollback()
        log_safe_exception(logger, exc, event="user_create_commit_failed")
        raise HTTPException(status_code=500, detail="Kunne ikke oprette bruger")

    try:
        await _send_password_reset_link(
            session,
            user_obj,
            request,
            purpose="activation",
            lockout_existing_password=False,
        )
    except Exception as exc:
        session.rollback()
        log_safe_exception(
            logger,
            exc,
            event="user_activation_email_failed",
            user_id=user_obj.id,
        )
        commit_audit_log(
            session,
            action="user_created",
            request=request,
            actor=admin,
            target_user=user_obj,
            entity_type="user",
            entity_id=user_obj.id,
            entity_label=user_obj.username,
            status="partial",
            details={
                "role": _role_label(user_obj.role),
                "organization_id": user_obj.organization_id,
                "activation_email_sent": False,
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Bruger blev oprettet, men aktiveringsmail kunne ikke sendes. Brug Send reset-link bagefter.",
        )

    add_audit_log(
        session,
        action="user_created",
        request=request,
        actor=admin,
        target_user=user_obj,
        entity_type="user",
        entity_id=user_obj.id,
        entity_label=user_obj.username,
        details={
            "role": _role_label(user_obj.role),
            "organization_id": user_obj.organization_id,
            "activation_email_sent": True,
        },
    )
    session.commit()
    session.refresh(user_obj)
    return user_obj


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    request: Request,
    user_id: int,
    user_update: UserUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Bruger ikke fundet")

    before_snapshot = {
        "username": user.username,
        "name": user.full_name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "organization_id": user.organization_id,
        "remarks": user.remarks,
        "last_login_at": _iso(getattr(user, "last_login_at", None)),
    }

    is_self = current_user.id == user_id
    update_fields = user_update.model_fields_set

    # Permanent/admin-password-reset må ikke foregå via PATCH.
    # Brug separat reset-link eller midlertidigt password, så admin aldrig ser
    # eller håndterer brugerens permanente adgangskode.
    if user_update.password is not None and not is_self:
        raise HTTPException(
            status_code=400,
            detail="Brug Send reset-link eller Midlertidigt password i stedet for direkte password-redigering",
        )

    # Ikke-admin må kun opdatere sig selv (kodeord + must_change_password)
    if not is_self and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Du har ikke adgang til at opdatere denne bruger")
    if is_self:
        non_self_fields = (
            user_update.role is not None
            or user_update.is_active is not None
            or user_update.organization_id is not None
            or user_update.full_name is not None
            or user_update.name is not None
            or user_update.remarks is not None
            or user_update.email is not None
        )
        if non_self_fields:
            raise HTTPException(
                status_code=403,
                detail="Du må kun ændre dit eget kodeord og sætte must_change_password til false",
            )

    if user_update.password is not None:
        forced_password_change = bool(is_self and getattr(user, "must_change_password", False))
        provided_old_password = user_update.old_password or user_update.current_password
        if not forced_password_change:
            if not provided_old_password:
                raise HTTPException(status_code=400, detail="Gammelt kodeord er påkrævet")
            if not verify_password(provided_old_password, user.hashed_password):
                raise HTTPException(status_code=400, detail="Gammelt kodeord er forkert")
        validate_password_strength(user_update.password)
        if verify_password(user_update.password, user.hashed_password):
            raise HTTPException(status_code=400, detail="Ny adgangskode må ikke være den samme som den gamle")
        user.hashed_password = get_password_hash(user_update.password)
        user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
        _revoke_all_user_refresh_tokens(session, user.id)
        user.must_change_password = False
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None

    if user_update.must_change_password is not None:
        if not is_self:
            raise HTTPException(status_code=400, detail="Tvunget adgangskodeskift styres via reset-link eller midlertidigt password")
        if user_update.must_change_password:
            raise HTTPException(status_code=403, detail="Du må ikke sætte must_change_password til true")
        if getattr(user, "must_change_password", False) and user_update.password is None:
            raise HTTPException(
                status_code=400,
                detail="Du skal vælge en ny adgangskode, før kravet om adgangskodeskift kan fjernes",
            )
        user.must_change_password = False

    # Tidlig retur for selvbetjening
    if is_self:
        after_snapshot = {
            "username": user.username,
            "name": user.full_name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "must_change_password": user.must_change_password,
            "organization_id": user.organization_id,
            "remarks": user.remarks,
            "last_login_at": _iso(getattr(user, "last_login_at", None)),
        }
        changed = _changed_fields(before_snapshot, after_snapshot)
        add_audit_log(
            session,
            action="password_changed" if user_update.password is not None else "user_updated",
            request=request,
            actor=current_user,
            target_user=user,
            entity_type="user",
            entity_id=user.id,
            entity_label=user.username,
            details={"self_service": True, "changed_fields": changed, "active_sessions_invalidated": user_update.password is not None},
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        if user_update.password is not None:
            await _send_password_changed_notification(db_user=user, request=request)
        return user

    # Admin-operationer herunder:
    _require_admin_has_organization(current_user)
    _require_can_manage_target(current_user, user)

    if "organization_id" in update_fields and not current_user.is_superadmin:
        if user_update.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Du kan kun tilknytte brugere til din egen organisation")

    next_role = user_update.role if user_update.role is not None else user.role
    next_org = user_update.organization_id if "organization_id" in update_fields else user.organization_id

    if user_update.role is not None:
        _require_role_assignment_allowed(current_user, user_update.role)
        # Last-superadmin guard: forhindre nedgradering af den sidst aktive superadmin
        if (
            user.role == "superadmin"
            and user.is_active
            and user_update.role != "superadmin"
            and _count_active_superadmins(session) <= 1
        ):
            raise HTTPException(
                status_code=400,
                detail="Kan ikke ændre rollen på den sidste aktive superadministrator",
            )

    normalized_org = _normalize_role_organization(next_role, next_org)
    if user_update.role is not None:
        user.role = user_update.role

    if user_update.is_active is not None:
        # Last-superadmin guard: forhindre deaktivering af den sidst aktive superadmin
        if (
            not user_update.is_active
            and user.role == "superadmin"
            and user.is_active
            and _count_active_superadmins(session) <= 1
        ):
            raise HTTPException(
                status_code=400,
                detail="Kan ikke deaktivere den sidste aktive superadministrator",
            )
        if user.is_active != user_update.is_active:
            user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
            _revoke_all_user_refresh_tokens(session, user.id)
            if not user_update.is_active:
                user.must_change_password = True
                user.password_reset_token_hash = None
                user.password_reset_expires_at = None
        user.is_active = user_update.is_active
    if user_update.role is not None or "organization_id" in update_fields:
        user.organization_id = normalized_org
        user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
        _revoke_all_user_refresh_tokens(session, user.id)
    if user_update.full_name is not None:
        user.full_name = user_update.full_name
    if user_update.name is not None:
        user.full_name = user_update.name
    if user_update.remarks is not None:
        user.remarks = user_update.remarks
    if user_update.email is not None:
        clean_email = user_update.email.strip().lower()
        if _user_identifier_exists(session, user.username, clean_email, exclude_user_id=user.id):
            raise HTTPException(status_code=400, detail="Email-adressen er allerede i brug")
        user.email = clean_email

    after_snapshot = {
        "username": user.username,
        "name": user.full_name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "organization_id": user.organization_id,
        "remarks": user.remarks,
        "last_login_at": _iso(getattr(user, "last_login_at", None)),
    }
    changed = _changed_fields(before_snapshot, after_snapshot)
    action = "user_updated"
    details = {"changed_fields": changed}
    if before_snapshot["role"] != after_snapshot["role"]:
        action = "role_changed"
        details.update({"role_before": _role_label(before_snapshot["role"]), "role_after": _role_label(after_snapshot["role"])})
    elif before_snapshot["email"] != after_snapshot["email"]:
        action = "email_changed"
    elif before_snapshot["is_active"] != after_snapshot["is_active"]:
        action = "user_activated" if after_snapshot["is_active"] else "user_deactivated"
        details.update({
            "active_sessions_invalidated": not after_snapshot["is_active"],
            "password_reset_token_cleared": not after_snapshot["is_active"],
        })

    add_audit_log(
        session,
        action=action,
        request=request,
        actor=current_user,
        target_user=user,
        entity_type="user",
        entity_id=user.id,
        entity_label=user.username,
        details=details,
    )

    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/users/{user_id}/reset-password", response_model=dict)
async def send_admin_reset_link(
    request: Request,
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_admin_user),
):
    enforce_request_rate_limit(
        request,
        bucket="password-reset-admin",
        max_attempts=10,
        window_seconds=60,
        detail="For mange reset-link forsøg. Prøv igen senere.",
    )

    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Bruger ikke fundet")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Du kan ikke sende nulstillingslink til dig selv her. Brug Skift adgangskode.")
    _require_admin_has_organization(current_user)
    _require_can_manage_target(current_user, target_user)
    if not target_user.is_active:
        raise HTTPException(status_code=400, detail="Brugeren er inaktiv")

    await _send_password_reset_link(
        session,
        target_user,
        request,
        purpose="admin_reset",
        lockout_existing_password=True,
    )
    add_audit_log(
        session,
        action="password_reset_link_sent_by_admin",
        request=request,
        actor=current_user,
        target_user=target_user,
        entity_type="user",
        entity_id=target_user.id,
        entity_label=target_user.username,
        details={"source": "admin_reset", "old_password_invalidated": True, "active_sessions_invalidated": True},
    )
    session.commit()
    return {"detail": "Nulstillingslink sendt"}


@router.post("/users/{user_id}/temporary-password", response_model=dict)
async def assign_temporary_password(
    request: Request,
    user_id: int,
    payload: AssignTemporaryPasswordRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_admin_user),
):
    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Bruger ikke fundet")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Du kan ikke tildele midlertidigt password til dig selv")
    _require_admin_has_organization(current_user)
    _require_can_manage_target(current_user, target_user)
    if not target_user.is_active:
        raise HTTPException(status_code=400, detail="Brugeren er inaktiv og skal aktiveres før midlertidigt password kan bruges")
    if verify_password(payload.temporary_password, target_user.hashed_password):
        raise HTTPException(status_code=400, detail="Nyt password må ikke være det samme som det gamle")

    target_user.hashed_password = get_password_hash(payload.temporary_password)
    target_user.must_change_password = True
    target_user.token_version = int(getattr(target_user, "token_version", 0) or 0) + 1
    _revoke_all_user_refresh_tokens(session, target_user.id)
    target_user.password_reset_token_hash = None
    target_user.password_reset_expires_at = None

    add_audit_log(
        session,
        action="temporary_password_assigned",
        request=request,
        actor=current_user,
        target_user=target_user,
        entity_type="user",
        entity_id=target_user.id,
        entity_label=target_user.username,
        details={"active_sessions_invalidated": True, "password_reset_token_cleared": True},
    )

    try:
        session.add(target_user)
        session.commit()
    except Exception as exc:
        session.rollback()
        log_safe_exception(logger, exc, event="temporary_password_commit_failed", user_id=user_id)
        raise HTTPException(status_code=500, detail="Kunne ikke tildele midlertidigt password")

    await _send_password_changed_notification(db_user=target_user, request=request)
    return {"detail": "Midlertidigt password er tildelt"}


@router.post("/users/{user_id}/permanent-delete", response_model=dict)
def permanently_delete_user(
    request: Request,
    user_id: int,
    payload: PermanentDeleteUserRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_admin_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Kun superadministrator kan slette brugere permanent")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Bruger ikke fundet")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Du kan ikke slette din egen bruger permanent")
    if user.role == "superadmin":
        raise HTTPException(status_code=400, detail="Superadministrator kan ikke slettes permanent")
    if user.is_active:
        raise HTTPException(status_code=400, detail="Brugeren skal være deaktiveret før permanent sletning")

    if (payload.confirmation_email or "").strip().lower() != (user.email or "").strip().lower():
        raise HTTPException(status_code=400, detail="Bekræftelses-email matcher ikke brugeren")

    deleted_snapshot = {
        "deleted_user_id": user.id,
        "username": user.username,
        "name": user.full_name,
        "email": user.email,
        "role": user.role,
        "organization_id": user.organization_id,
        "last_login_at": _iso(getattr(user, "last_login_at", None)),
    }

    # Fjern/ryd relationer, der ellers ville blokere permanent sletning.
    # AuditLog bruger snapshot-felter uden ForeignKey, så historikken overlever.
    session.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    session.execute(
        update(EnrollmentToken)
        .where(EnrollmentToken.created_by_user_id == user.id)
        .values(created_by_user_id=None)
    )
    session.execute(
        update(OrganizationLogo)
        .where(OrganizationLogo.uploaded_by_user_id == user.id)
        .values(uploaded_by_user_id=None)
    )

    add_audit_log(
        session,
        action="user_permanently_deleted",
        request=request,
        actor=current_user,
        target_user_id=user.id,
        target_username=user.username,
        target_organization_id=user.organization_id,
        entity_type="user",
        entity_id=user.id,
        entity_label=user.username,
        details={
            "deleted_user": deleted_snapshot,
            "refresh_tokens_deleted": True,
            "foreign_key_references_detached": [
                "enrollmenttoken.created_by_user_id",
                "organizationlogo.uploaded_by_user_id",
                "terminal_session.requested_by_user_id",
                "root_terminal_grant.user_id",
                "terminal_session_event.actor_user_id",
                "remote_desktop_session.requested_by_user_id",
                "remote_desktop_session_event.actor_user_id",
                "client_command.requested_by_user_id",
            ],
            "domain_session_history_preserved": True,
        },
    )

    session.delete(user)
    session.commit()
    return {"detail": "Bruger slettet permanent", "deleted_user_id": user_id, "username": deleted_snapshot.get("username")}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    request: Request,
    user_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin_user),
):
    """Bagudkompatibel DELETE-route, som sikkert deaktiverer i stedet for hard delete.

    Permanent sletning kræver fortsat den særskilte superadmin-route med
    emailbekræftelse. Dermed kan gamle frontend-bundles ikke omgå den aftalte
    deaktiverings- og audit-kontrakt.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Bruger ikke fundet")

    _require_admin_has_organization(admin)
    _require_can_manage_target(admin, user)

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Du kan ikke deaktivere din egen bruger")

    if (
        user.role == "superadmin"
        and user.is_active
        and _count_active_superadmins(session) <= 1
    ):
        raise HTTPException(
            status_code=400,
            detail="Kan ikke deaktivere den sidste aktive superadministrator",
        )

    if not user.is_active:
        return None

    user.is_active = False
    user.must_change_password = True
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None
    _revoke_all_user_refresh_tokens(session, user.id)

    add_audit_log(
        session,
        action="user_deactivated",
        request=request,
        actor=admin,
        target_user=user,
        entity_type="user",
        entity_id=user.id,
        entity_label=user.username,
        details={
            "source": "legacy_delete_route",
            "active_sessions_invalidated": True,
            "password_reset_token_cleared": True,
        },
    )
    session.add(user)
    session.commit()
    return None
