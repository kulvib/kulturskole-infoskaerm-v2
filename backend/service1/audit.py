from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Request
from sqlmodel import Session

from .models import AuditLog, User
from .client_ip import get_client_ip
from .observability import get_bound_request_id, log_safe_exception

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        logger.warning("Ugyldig %s. Bruger standardværdi %s", name, default)
        return default
    return max(minimum, min(maximum, value))


# Audit-log gemmes som standard i 90 dage. Værdien kan justeres i Render via
# AUDIT_LOG_RETENTION_DAYS, men oprydning sker bevidst manuelt via API/UI.
AUDIT_LOG_RETENTION_DAYS = _env_int(
    "AUDIT_LOG_RETENTION_DAYS",
    90,
    minimum=90,
    maximum=3650,
)

CRITICAL_AUDIT_ACTIONS = {
    "role_changed",
    "email_changed",
    "user_permanently_deleted",
    "password_reset_completed",
    "password_reset_link_sent_by_admin",
    "temporary_password_assigned",
    "client_secret_rotated",
    "client_secret_revoked",
    "client_permanently_deleted",
    "organization_deleted",
    "organization_season_calendars_replaced",
}

WARNING_AUDIT_ACTIONS = {
    "user_deactivated",
    "login_failed",
    "client_soft_deleted",
    "enrollment_token_revoked",
}


def default_audit_severity(action: str, status: str = "success") -> str:
    if action in CRITICAL_AUDIT_ACTIONS:
        return "critical"
    if status and status not in {"success", "ok", "completed"}:
        return "warning"
    if action in WARNING_AUDIT_ACTIONS:
        return "warning"
    return "info"


def default_audit_is_critical(action: str, severity: Optional[str] = None) -> bool:
    return action in CRITICAL_AUDIT_ACTIONS or severity == "critical"


def default_retain_until(retention_days: int = AUDIT_LOG_RETENTION_DAYS) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=retention_days)


def _role_label(user: Optional[User]) -> Optional[str]:
    if user is None:
        return None
    role = getattr(user, "role", None)
    return {
        "superadmin": "superadministrator",
        "admin": "administrator",
        "viewer": "viewer",
        "bruger": "bruger",
    }.get(role, role or None)


def _request_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    value = get_client_ip(request)
    return value if value != "unknown" else None


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    value = request.headers.get("user-agent")
    return value[:1000] if value else None


def make_user_snapshot(user: Optional[User]) -> dict[str, Any]:
    if user is None:
        return {
            "user_id": None,
            "username": None,
            "role": None,
            "organization_id": None,
        }
    return {
        "user_id": getattr(user, "id", None),
        "username": getattr(user, "username", None),
        "role": _role_label(user),
        "organization_id": getattr(user, "organization_id", None),
    }


def add_audit_log(
    db: Session,
    *,
    action: str,
    request: Optional[Request] = None,
    actor: Optional[User] = None,
    target_user: Optional[User] = None,
    target_user_id: Optional[int] = None,
    target_username: Optional[str] = None,
    target_organization_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_label: Optional[str] = None,
    status: str = "success",
    severity: Optional[str] = None,
    is_critical: Optional[bool] = None,
    retention_days: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
) -> AuditLog:
    """Tilføj en audit-log til den aktuelle DB-session.

    Funktionen committer ikke selv. Kald den før endpointets normale commit, så
    audit-log og ændringen gemmes i samme transaktion.
    """
    actor_snapshot = make_user_snapshot(actor)

    if target_user is not None:
        target_user_id = getattr(target_user, "id", target_user_id)
        target_username = getattr(target_user, "username", target_username)
        target_organization_id = getattr(target_user, "organization_id", target_organization_id)

    resolved_severity = severity or default_audit_severity(action, status)
    resolved_is_critical = (
        default_audit_is_critical(action, resolved_severity)
        if is_critical is None
        else bool(is_critical)
    )
    resolved_retention_days = retention_days or AUDIT_LOG_RETENTION_DAYS

    audit_log = AuditLog(
        action=action,
        status=status,
        actor_user_id=actor_snapshot["user_id"],
        actor_username=actor_snapshot["username"],
        actor_role=actor_snapshot["role"],
        actor_organization_id=actor_snapshot["organization_id"],
        target_user_id=target_user_id,
        target_username=target_username,
        target_organization_id=target_organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        request_id=get_bound_request_id(request),
        request_ip=_request_ip(request),
        user_agent=_user_agent(request),
        severity=resolved_severity,
        is_critical=resolved_is_critical,
        retention_days=resolved_retention_days,
        retain_until=default_retain_until(resolved_retention_days),
        details=details or None,
    )
    db.add(audit_log)
    return audit_log


def commit_audit_log(
    db: Session,
    *,
    action: str,
    request: Optional[Request] = None,
    actor: Optional[User] = None,
    target_user: Optional[User] = None,
    target_user_id: Optional[int] = None,
    target_username: Optional[str] = None,
    target_organization_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_label: Optional[str] = None,
    status: str = "success",
    severity: Optional[str] = None,
    is_critical: Optional[bool] = None,
    retention_days: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Gem en audit-log i en separat commit uden at blokere brugerflowet."""
    try:
        add_audit_log(
            db,
            action=action,
            request=request,
            actor=actor,
            target_user=target_user,
            target_user_id=target_user_id,
            target_username=target_username,
            target_organization_id=target_organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=entity_label,
            status=status,
            severity=severity,
            is_critical=is_critical,
            retention_days=retention_days,
            details=details,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        log_safe_exception(logger, exc, event="audit_log_commit_failed", action=action)
