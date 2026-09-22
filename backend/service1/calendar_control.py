"""Canonical Calendar delivery for the Display domain.

Calendar data remains durable backend state.  An authenticated Display-domain
client receives only its own current/next season calendars and evaluates the
wall-clock schedule locally so short backend outages do not break transitions.

Step 56A adds a lightweight delivery validator so unchanged 15-second polls do
not have to read the large JSONB calendar payload from PostgreSQL/Neon.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, Iterable

from fastapi import HTTPException
from sqlmodel import Session, select

from .models import CalendarMarking, Client
from .season_service import (
    SeasonValidationError,
    current_and_next_seasons,
    validate_and_normalize_markings,
)

CALENDAR_DELIVERY_SCHEMA_VERSION = 1
CALENDAR_ETAG_PREFIX = "cfcal-"


def _revision_for(seasons: dict[str, dict[str, dict[str, str]]]) -> str:
    payload = json.dumps(
        seasons,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timestamp_token(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    return str(value or "")


def _delivery_etag_from_rows(
    requested_seasons: tuple[str, ...],
    rows: Iterable[tuple[Any, ...]],
) -> str | None:
    """Return a strong ETag from lightweight row metadata.

    The row id + ORM-maintained ``updated_at`` changes whenever a CalendarMarking
    row is inserted/replaced/updated.  Season names are included so the validator
    also changes automatically when ``current_and_next_seasons`` rolls forward,
    even if no calendar row is edited at that exact moment.
    """
    metadata: dict[str, tuple[int, str]] = {}
    for row in rows:
        row_id, season, updated_at = row[0], row[1], row[-1]
        if row_id is None:
            return None
        metadata[str(season)] = (int(row_id), _timestamp_token(updated_at))
    if any(season not in metadata for season in requested_seasons):
        return None
    encoded = json.dumps(
        [[season, metadata[season][0], metadata[season][1]] for season in requested_seasons],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f'"{CALENDAR_ETAG_PREFIX}{digest}"'


def _validate_authorized_client(
    session: Session,
    *,
    client_id: int,
    authorized_client: Client | None,
) -> Client:
    client = authorized_client
    if client is None:
        # Safe standalone fallback: callers that have not just passed the canonical
        # Display authorization boundary still receive the historical lifecycle check.
        client = session.get(Client, client_id)
        if client is None or getattr(client, "deleted_at", None) is not None:
            raise HTTPException(status_code=404, detail="Klient ikke fundet")
        if str(getattr(client, "status", "") or "").strip().lower() != "approved":
            raise HTTPException(status_code=409, detail="Klienten er ikke aktiveret")
    elif int(getattr(client, "id", 0) or 0) != int(client_id):
        raise HTTPException(status_code=403, detail="Autoriseret klient matcher ikke kalenderklienten")
    return client


def display_calendar_delivery_etag(
    session: Session,
    *,
    client_id: int,
    authorized_client: Client | None = None,
) -> str | None:
    """Return the current delivery ETag without selecting ``markings`` JSONB."""
    _validate_authorized_client(
        session,
        client_id=client_id,
        authorized_client=authorized_client,
    )
    requested_seasons = tuple(current_and_next_seasons())
    rows = session.exec(
        select(CalendarMarking.id, CalendarMarking.season, CalendarMarking.updated_at).where(
            CalendarMarking.client_id == client_id,
            CalendarMarking.season.in_(requested_seasons),
        )
    ).all()
    return _delivery_etag_from_rows(requested_seasons, rows)


def build_display_calendar_delivery_with_etag(
    session: Session,
    *,
    client_id: int,
    authorized_client: Client | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Return a complete calendar snapshot plus its lightweight HTTP validator."""
    _validate_authorized_client(
        session,
        client_id=client_id,
        authorized_client=authorized_client,
    )

    requested_seasons = tuple(current_and_next_seasons())
    rows = session.exec(
        select(
            CalendarMarking.id,
            CalendarMarking.season,
            CalendarMarking.markings,
            CalendarMarking.updated_at,
        ).where(
            CalendarMarking.client_id == client_id,
            CalendarMarking.season.in_(requested_seasons),
        )
    ).all()
    markings_by_season = {str(season): markings for _, season, markings, _ in rows}

    seasons: dict[str, dict[str, dict[str, str]]] = {}
    for season in requested_seasons:
        markings = markings_by_season.get(season)
        if markings is None:
            raise HTTPException(
                status_code=409,
                detail=f"Kalenderen mangler for sæson {season}",
            )
        try:
            seasons[season] = validate_and_normalize_markings(
                markings,
                season,
                require_complete=True,
            )
        except SeasonValidationError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Kalenderen er ufuldstændig for sæson {season}: {exc}",
            ) from exc

    payload = {
        "schema_version": CALENDAR_DELIVERY_SCHEMA_VERSION,
        "client_id": client_id,
        "revision": _revision_for(seasons),
        "seasons": seasons,
    }
    return payload, _delivery_etag_from_rows(requested_seasons, rows)


def build_display_calendar_delivery(
    session: Session,
    *,
    client_id: int,
    authorized_client: Client | None = None,
) -> dict[str, Any]:
    """Backward-compatible complete snapshot helper used by focused callers/tests."""
    payload, _ = build_display_calendar_delivery_with_etag(
        session,
        client_id=client_id,
        authorized_client=authorized_client,
    )
    return payload
