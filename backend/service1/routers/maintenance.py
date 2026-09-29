from __future__ import annotations

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from ..audit import add_audit_log, commit_audit_log
from ..auth import get_current_user, verify_password
from ..db import get_session
from ..maintenance_state import MaintenanceSnapshot, get_maintenance_snapshot, update_maintenance_cache
from ..models import MaintenanceState, User
from ..rate_limit import assert_key_not_limited, clear_key_rate_limit, record_key_attempt
from ..observability import log_safe_exception

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
logger = logging.getLogger(__name__)


class MaintenanceStatusOut(BaseModel):
    enabled: bool
    message: str | None = None
    expected_end_at: datetime | None = None
    enabled_at: datetime | None = None


class MaintenanceUpdateRequest(BaseModel):
    enabled: bool
    password: str = Field(min_length=1, max_length=256)
    message: str | None = Field(default=None, max_length=500)
    expected_end_at: datetime | None = None

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = " ".join(value.split()).strip()
        return clean or None


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _to_out(row: MaintenanceState | MaintenanceSnapshot | None) -> MaintenanceStatusOut:
    if row is None:
        return MaintenanceStatusOut(enabled=False)
    return MaintenanceStatusOut(
        enabled=bool(row.enabled),
        message=row.message,
        expected_end_at=_as_aware_utc(row.expected_end_at),
        enabled_at=_as_aware_utc(row.enabled_at),
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


def _require_password(request: Request, session: Session, actor: User, password: str) -> None:
    key = f"user:{int(actor.id)}"
    assert_key_not_limited(
        bucket="maintenance-password",
        key=key,
        max_attempts=5,
        window_seconds=300,
        detail="For mange mislykkede godkendelsesforsøg. Prøv igen senere.",
    )
    if not verify_password(password, actor.hashed_password):
        record_key_attempt(bucket="maintenance-password", key=key, window_seconds=300)
        commit_audit_log(
            session,
            action="maintenance_reauthentication_failed",
            request=request,
            actor=actor,
            target_user=actor,
            entity_type="maintenance_state",
            entity_id=1,
            status="failed",
            severity="warning",
            details={"reason": "wrong_password"},
        )
        raise HTTPException(status_code=403, detail="Adgangskoden er forkert")
    clear_key_rate_limit(bucket="maintenance-password", key=key)


@router.get("/status", response_model=MaintenanceStatusOut)
def get_maintenance_status(
    response: Response,
    session: Session = Depends(get_session),
) -> MaintenanceStatusOut:
    _no_store(response)
    try:
        return _to_out(get_maintenance_snapshot(session))
    except Exception as exc:
        log_safe_exception(
            logger,
            exc,
            event="maintenance_status_unavailable",
            location="maintenance.get_maintenance_status",
        )
        raise HTTPException(
            status_code=503,
            detail="Vedligeholdelsestilstanden kunne ikke bekræftes",
            headers={"Cache-Control": "no-store, max-age=0"},
        ) from None


@router.put("", response_model=MaintenanceStatusOut)
def update_maintenance_status(
    payload: MaintenanceUpdateRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> MaintenanceStatusOut:
    actor = getattr(request.state, "real_actor", None) or current_user
    if getattr(request.state, "impersonation_active", False) or actor.id != current_user.id:
        raise HTTPException(status_code=409, detail="Afslut det aktive bruger-skift først")
    if not actor.is_superadmin:
        raise HTTPException(status_code=403, detail="Kun superadministrator kan styre vedligeholdelsestilstand")

    _require_password(request, session, actor, payload.password)
    now_aware = datetime.now(timezone.utc)
    expected = _as_aware_utc(payload.expected_end_at)
    if payload.enabled and expected is not None and expected <= now_aware:
        raise HTTPException(status_code=400, detail="Forventet åbning skal ligge i fremtiden")

    row = session.exec(select(MaintenanceState).where(MaintenanceState.id == 1).with_for_update()).first()
    if row is None:
        row = MaintenanceState(id=1, enabled=False)
        session.add(row)
        session.flush()

    changed = bool(row.enabled) != payload.enabled
    row.enabled = payload.enabled
    row.message = payload.message if payload.enabled else None
    row.expected_end_at = (
        expected.replace(tzinfo=None) if payload.enabled and expected is not None else None
    )
    row.enabled_at = (
        now_aware.replace(tzinfo=None)
        if payload.enabled and changed
        else (row.enabled_at if payload.enabled else None)
    )
    row.enabled_by_user_id = int(actor.id) if payload.enabled else None
    row.updated_at = now_aware.replace(tzinfo=None)
    session.add(row)
    add_audit_log(
        session,
        action="maintenance_enabled" if payload.enabled else "maintenance_disabled",
        request=request,
        actor=actor,
        target_user=actor,
        entity_type="maintenance_state",
        entity_id=1,
        entity_label="human-user-access",
        severity="critical" if payload.enabled else "warning",
        is_critical=payload.enabled,
        details={
            "enabled": payload.enabled,
            "expected_end_at": expected.isoformat() if expected else None,
            "scope": "human_user_access_only",
        },
    )
    try:
        session.commit()
        session.refresh(row)
    except Exception:
        session.rollback()
        raise HTTPException(status_code=500, detail="Kunne ikke ændre vedligeholdelsestilstand")

    update_maintenance_cache(row)
    _no_store(response)
    return _to_out(row)
