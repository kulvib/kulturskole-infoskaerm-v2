import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from ..auth import (
    get_current_admin_user,
    get_current_superadmin_user,
    get_current_user,
    get_current_user_or_client,
    principal_is_client,
    require_client_self_or_user,
)
from ..db import get_session
from ..models import CalendarMarking, Client, Organization, OrganizationSeasonTimes
from ..observability import log_safe_exception
from ..season_service import (
    SeasonValidationError,
    current_and_next_seasons,
    current_season_payload,
    maintain_current_and_next_seasons,
    season_dates,
    season_metadata,
    validate_and_normalize_markings,
    validate_supported_season,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class MarkedDaysRequest(BaseModel):
    markedDays: Dict[str, Dict[str, Any]]
    clients: List[int]
    season: str


class SeasonReadinessResponse(BaseModel):
    organization_id: int
    season: str
    is_current: bool
    is_next: bool
    season_times_configured: bool
    approved_clients: int
    calendars_present: int
    complete_calendars: int
    missing_calendars: int
    incomplete_calendars: int
    missing_days: int
    is_ready: bool


def _validated_supported_season(season: str) -> str:
    try:
        return validate_supported_season(season)
    except SeasonValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/calendar/marked-days")
def save_marked_days(
    data: MarkedDaysRequest,
    session=Depends(get_session),
    user=Depends(get_current_user),
):
    if getattr(user, "role", None) == "viewer":
        raise HTTPException(status_code=403, detail="Se adgang har kun læseadgang")
    if getattr(user, "role", None) not in {"superadmin", "admin", "bruger"}:
        raise HTTPException(status_code=403, detail="Du har ikke adgang til at gemme kalenderdage")

    season = _validated_supported_season(data.season)
    clients: list[Client] = []
    for client_id in data.clients:
        client = session.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail=f"Klient {client_id} ikke fundet")
        if not getattr(user, "is_superadmin", False) and client.organization_id != user.organization_id:
            raise HTTPException(status_code=403, detail="Du har kun adgang til klienter i din egen organisation")
        clients.append(client)

    normalized_by_client: dict[int, Dict[str, Dict[str, str]]] = {}
    try:
        for client in clients:
            normalized_by_client[int(client.id)] = validate_and_normalize_markings(
                data.markedDays.get(str(client.id), {}),
                season,
                require_complete=True,
            )
    except SeasonValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        for client in clients:
            client_id = int(client.id)
            markings = normalized_by_client[client_id]
            existing = session.exec(
                select(CalendarMarking).where(
                    CalendarMarking.season == season,
                    CalendarMarking.client_id == client_id,
                )
            ).first()
            if existing:
                existing.markings = markings
                session.add(existing)
            else:
                session.add(
                    CalendarMarking(
                        season=season,
                        client_id=client_id,
                        markings=markings,
                    )
                )
        session.commit()
        return {"ok": True, "delivery": "client_poll"}
    except SQLAlchemyError as exc:
        session.rollback()
        log_safe_exception(
            logger,
            exc,
            event="calendar_save_failed",
            client_count=len(data.clients),
        )
        raise HTTPException(status_code=500, detail="Kunne ikke gemme kalenderen") from exc


@router.get("/calendar/marked-days")
def get_marked_days(
    season: str = Query(..., description="Sæson fx '2025/2026'"),
    client_id: int = Query(...),
    start_date: Optional[str] = Query(None, description="Filtrer fra dato (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Filtrer til dato (YYYY-MM-DD)"),
    session=Depends(get_session),
    principal=Depends(get_current_user_or_client),
):
    season = _validated_supported_season(season)
    require_client_self_or_user(principal, client_id)
    if not principal_is_client(principal):
        client = session.get(Client, client_id)
        if not client:
            raise HTTPException(status_code=404, detail="Klient ikke fundet")
        if not getattr(principal, "is_superadmin", False) and client.organization_id != principal.organization_id:
            raise HTTPException(status_code=403, detail="Du har kun adgang til klienter i din egen organisation")

    existing = session.exec(
        select(CalendarMarking).where(
            CalendarMarking.season == season,
            CalendarMarking.client_id == client_id,
        )
    ).first()
    markings = existing.markings if existing else {}
    formatted: Dict[str, Any] = {}
    for key, value in (markings or {}).items():
        iso_date = str(key)[:10]
        if start_date and iso_date < start_date:
            continue
        if end_date and iso_date > end_date:
            continue
        formatted[f"{iso_date}T00:00:00"] = value
    return {"markedDays": formatted}


@router.get("/calendar/seasons")
def get_seasons_list(principal=Depends(get_current_user_or_client)):
    """Return exactly the authoritative current and next season."""
    del principal  # Authentication is the purpose of the dependency.
    return [season_metadata(season) for season in current_and_next_seasons()]


@router.get("/calendar/season")
def get_current_season(principal=Depends(get_current_user_or_client)):
    del principal
    return current_season_payload()


@router.get("/calendar/seasons/readiness", response_model=SeasonReadinessResponse)
def get_season_readiness(
    organization_id: int = Query(...),
    season: str = Query(...),
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    """Read-only readiness check inspired by Flow's season preparation guard.

    Display creates current/next season data automatically. This endpoint does
    not repair or mutate anything; it verifies that the automatic contract is
    complete for one organization and makes exceptional gaps visible before
    the 1 August rollover.
    """
    normalized_season = _validated_supported_season(season)
    current, next_season = current_and_next_seasons()

    if not getattr(admin, "is_superadmin", False) and admin.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Du har kun adgang til din egen organisation")

    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")

    season_times = session.exec(
        select(OrganizationSeasonTimes).where(
            OrganizationSeasonTimes.organization_id == organization_id,
            OrganizationSeasonTimes.season == normalized_season,
        )
    ).first()

    approved_clients = session.exec(
        select(Client).where(
            Client.organization_id == organization_id,
            Client.status == "approved",
            Client.deleted_at == None,  # noqa: E711 - SQLModel expression
        )
    ).all()
    client_ids = [int(client.id) for client in approved_clients if client.id is not None]

    calendar_rows = []
    if client_ids:
        calendar_rows = session.exec(
            select(CalendarMarking).where(
                CalendarMarking.client_id.in_(client_ids),
                CalendarMarking.season == normalized_season,
            )
        ).all()
    calendars_by_client = {int(row.client_id): row for row in calendar_rows}

    expected_dates = {item.isoformat() for item in season_dates(normalized_season)}
    complete_calendars = 0
    incomplete_calendars = 0
    missing_days = 0

    for client_id in client_ids:
        row = calendars_by_client.get(client_id)
        if row is None:
            missing_days += len(expected_dates)
            continue

        markings = row.markings if isinstance(row.markings, dict) else {}
        present_dates: set[str] = set()
        for raw_key in markings:
            candidate = str(raw_key)[:10]
            try:
                parsed = date.fromisoformat(candidate)
            except ValueError:
                continue
            canonical = parsed.isoformat()
            if canonical in expected_dates:
                present_dates.add(canonical)
        missing_days += len(expected_dates - present_dates)

        try:
            validate_and_normalize_markings(
                markings,
                normalized_season,
                require_complete=True,
            )
        except SeasonValidationError:
            incomplete_calendars += 1
        else:
            complete_calendars += 1

    calendars_present = len(calendars_by_client)
    missing_calendars = len(client_ids) - calendars_present
    is_ready = (
        season_times is not None
        and missing_calendars == 0
        and incomplete_calendars == 0
        and complete_calendars == len(client_ids)
    )

    return SeasonReadinessResponse(
        organization_id=organization_id,
        season=normalized_season,
        is_current=normalized_season == current,
        is_next=normalized_season == next_season,
        season_times_configured=season_times is not None,
        approved_clients=len(client_ids),
        calendars_present=calendars_present,
        complete_calendars=complete_calendars,
        missing_calendars=missing_calendars,
        incomplete_calendars=incomplete_calendars,
        missing_days=missing_days,
        is_ready=is_ready,
    )


@router.post("/calendar/cleanup-past-seasons")
def cleanup_past_seasons(
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    del user
    try:
        summary = maintain_current_and_next_seasons(session)
        session.commit()
        return summary
    except Exception as exc:
        session.rollback()
        log_safe_exception(logger, exc, event="season_maintenance_manual_failed")
        raise HTTPException(status_code=500, detail="Kunne ikke vedligeholde sæsondata") from exc
