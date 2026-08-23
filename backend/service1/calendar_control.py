"""Canonical Calendar delivery for the Display domain.

Calendar data remains durable backend state.  An authenticated Display-domain
client receives only its own current/next season calendars and evaluates the
wall-clock schedule locally so short backend outages do not break transitions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from .models import CalendarMarking, Client
from .season_service import (
    SeasonValidationError,
    current_and_next_seasons,
    validate_and_normalize_markings,
)

CALENDAR_DELIVERY_SCHEMA_VERSION = 1


def _revision_for(seasons: dict[str, dict[str, dict[str, str]]]) -> str:
    payload = json.dumps(
        seasons,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_display_calendar_delivery(session: Session, *, client_id: int) -> dict[str, Any]:
    """Return a complete, self-only calendar snapshot for one Display agent.

    Current and next season must both be complete before a new snapshot is
    delivered.  The client keeps its last already-validated cache on a 409, so
    an incomplete backend edit cannot replace known-good local schedule bytes.
    """
    client = session.get(Client, client_id)
    if client is None or getattr(client, "deleted_at", None) is not None:
        raise HTTPException(status_code=404, detail="Klient ikke fundet")
    if str(getattr(client, "status", "") or "").strip().lower() != "approved":
        raise HTTPException(status_code=409, detail="Klienten er ikke aktiveret")

    seasons: dict[str, dict[str, dict[str, str]]] = {}
    for season in current_and_next_seasons():
        row = session.exec(
            select(CalendarMarking).where(
                CalendarMarking.client_id == client_id,
                CalendarMarking.season == season,
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=409,
                detail=f"Kalenderen mangler for sæson {season}",
            )
        try:
            seasons[season] = validate_and_normalize_markings(
                row.markings,
                season,
                require_complete=True,
            )
        except SeasonValidationError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Kalenderen er ufuldstændig for sæson {season}: {exc}",
            ) from exc

    return {
        "schema_version": CALENDAR_DELIVERY_SCHEMA_VERSION,
        "client_id": client_id,
        "revision": _revision_for(seasons),
        "seasons": seasons,
    }
