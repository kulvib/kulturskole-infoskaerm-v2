"""Authoritative season and calendar contract for PlanIQ Display.

A season always runs from 1 August through 31 July in Europe/Copenhagen.
The runtime maintains exactly the current and next season for every approved
client. Existing calendar choices are preserved; only missing dates are filled
from the effective organization standard.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, text
from sqlmodel import select

from .models import CalendarMarking, Client, Organization, OrganizationSeasonTimes

DK_TIMEZONE_NAME = "Europe/Copenhagen"
DK_TIMEZONE = ZoneInfo(DK_TIMEZONE_NAME)
SEASON_MAINTENANCE_LOCK_KEY = -614927384150371239

DAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

SYSTEM_DEFAULT_DAY_TIMES: Dict[str, Dict[str, str]] = {
    "monday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "tuesday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "wednesday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "thursday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "friday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "saturday": {"status": "off"},
    "sunday": {"status": "off"},
}

OFF_DAY_STATUSES = {
    "off", "closed", "lukket", "slukket", "false", "0", "nej", "no",
}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
SEASON_RE = re.compile(r"^(\d{4})/(\d{4})$")


class SeasonValidationError(ValueError):
    """Raised when season or calendar data violates the season contract."""


def copy_system_default_day_times() -> Dict[str, Dict[str, str]]:
    return deepcopy(SYSTEM_DEFAULT_DAY_TIMES)


def now_copenhagen(value: Optional[datetime] = None) -> datetime:
    if value is None:
        return datetime.now(DK_TIMEZONE)
    if value.tzinfo is None:
        return value.replace(tzinfo=DK_TIMEZONE)
    return value.astimezone(DK_TIMEZONE)


def today_copenhagen(value: Optional[datetime | date] = None) -> date:
    if value is None:
        return now_copenhagen().date()
    if isinstance(value, datetime):
        return now_copenhagen(value).date()
    return value


def season_start_for_date(value: date) -> int:
    return value.year if value.month >= 8 else value.year - 1


def season_string(start_year: int) -> str:
    return f"{start_year:04d}/{start_year + 1:04d}"


def current_season(value: Optional[datetime | date] = None) -> str:
    return season_string(season_start_for_date(today_copenhagen(value)))


def current_and_next_seasons(value: Optional[datetime | date] = None) -> tuple[str, str]:
    start = season_start_for_date(today_copenhagen(value))
    return season_string(start), season_string(start + 1)


def parse_season(season: str) -> tuple[int, int]:
    match = SEASON_RE.fullmatch(str(season or "").strip())
    if not match:
        raise SeasonValidationError("Ugyldig sæson — brug format '2025/2026'")
    start, end = int(match.group(1)), int(match.group(2))
    if end != start + 1:
        raise SeasonValidationError("Ugyldig sæson — slut-år skal være start-år + 1")
    if start < 1900 or end > 9999:
        raise SeasonValidationError("Ugyldig sæson — årstallene er uden for det understøttede interval")
    return start, end


def validate_season(season: str) -> str:
    start, end = parse_season(season)
    return f"{start:04d}/{end:04d}"


def validate_supported_season(
    season: str,
    value: Optional[datetime | date] = None,
) -> str:
    normalized = validate_season(season)
    if normalized not in current_and_next_seasons(value):
        raise SeasonValidationError("Kun nuværende og næste sæson kan anvendes")
    return normalized


def season_bounds(season: str) -> tuple[date, date]:
    start, end = parse_season(season)
    return date(start, 8, 1), date(end, 7, 31)


def season_dates(season: str) -> list[date]:
    start, end = season_bounds(season)
    count = (end - start).days + 1
    return [start + timedelta(days=offset) for offset in range(count)]


def next_season_switch_at(value: Optional[datetime | date] = None) -> datetime:
    start = season_start_for_date(today_copenhagen(value))
    return datetime(start + 1, 8, 1, 0, 0, tzinfo=DK_TIMEZONE)


def season_metadata(
    season: str,
    value: Optional[datetime | date] = None,
) -> Dict[str, Any]:
    normalized = validate_season(season)
    start, end = season_bounds(normalized)
    current, _next = current_and_next_seasons(value)
    return {
        "id": normalized,
        "label": normalized,
        "season": normalized,
        "isCurrent": normalized == current,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def current_season_payload(value: Optional[datetime] = None) -> Dict[str, Any]:
    local_now = now_copenhagen(value)
    current, next_season = current_and_next_seasons(local_now)
    payload = season_metadata(current, local_now)
    payload.update({
        "next_season": next_season,
        "timezone": DK_TIMEZONE_NAME,
        "server_time_utc": local_now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "next_switch_at": next_season_switch_at(local_now).isoformat(),
    })
    return payload


def seconds_until_next_daily_maintenance(
    value: Optional[datetime] = None,
    *,
    hour: int = 0,
    minute: int = 5,
) -> float:
    local_now = now_copenhagen(value)
    next_run = datetime.combine(local_now.date(), time(hour, minute), tzinfo=DK_TIMEZONE)
    if next_run <= local_now:
        next_run += timedelta(days=1)
    return max(60.0, (next_run - local_now).total_seconds())


def is_off_day(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    status = str(value.get("status") or value.get("state") or "on").strip().lower()
    return status in OFF_DAY_STATUSES or value.get("enabled") is False


def normalize_day_times(value: Any) -> Dict[str, Dict[str, str]]:
    source = value if isinstance(value, dict) else {}
    normalized: Dict[str, Dict[str, str]] = {}

    for key in DAY_KEYS:
        fallback = SYSTEM_DEFAULT_DAY_TIMES[key]
        raw = source.get(key)
        if not isinstance(raw, dict):
            raw = fallback

        if is_off_day(raw):
            normalized[key] = {"status": "off"}
            continue

        on_time = str(raw.get("onTime") or fallback.get("onTime") or "09:00").strip()
        off_time = str(raw.get("offTime") or fallback.get("offTime") or "20:00").strip()
        if not TIME_RE.fullmatch(on_time) or not TIME_RE.fullmatch(off_time):
            raise SeasonValidationError(f"{key}: tider skal være på formatet hh:mm")
        if on_time > off_time:
            raise SeasonValidationError(f"{key}: tænd-tid skal være før sluk-tid")
        normalized[key] = {"status": "on", "onTime": on_time, "offTime": off_time}

    return normalized


def day_key_for_date(value: date) -> str:
    return DAY_KEYS[value.weekday()]


def calendar_entry_for_standard(standard: Dict[str, str]) -> Dict[str, str]:
    if is_off_day(standard):
        return {"status": "off"}
    return {
        "status": "on",
        "onTime": str(standard["onTime"]),
        "offTime": str(standard["offTime"]),
    }


def normalize_calendar_entry(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise SeasonValidationError("Kalenderdagen skal være et objekt")
    if is_off_day(value):
        return {"status": "off"}

    status = str(value.get("status") or "on").strip().lower()
    if status not in {"on", "open", "active", "tændt", "true", "1", "ja", "yes"}:
        raise SeasonValidationError("Kalenderdagens status skal være 'on' eller 'off'")
    on_time = str(value.get("onTime") or "").strip()
    off_time = str(value.get("offTime") or "").strip()
    if not TIME_RE.fullmatch(on_time) or not TIME_RE.fullmatch(off_time):
        raise SeasonValidationError("Kalendertider skal være på formatet hh:mm")
    if on_time > off_time:
        raise SeasonValidationError("Tænd-tid skal være før sluk-tid")
    return {"status": "on", "onTime": on_time, "offTime": off_time}


def parse_calendar_date_key(key: str) -> date:
    raw = str(key or "").strip()
    if not raw:
        raise SeasonValidationError("Kalenderen indeholder en tom dato")
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except (TypeError, ValueError) as exc:
        raise SeasonValidationError(f"Ugyldig kalenderdato: {raw}") from exc


def validate_and_normalize_markings(
    markings: Any,
    season: str,
    *,
    require_complete: bool = True,
) -> Dict[str, Dict[str, str]]:
    normalized_season = validate_season(season)
    if not isinstance(markings, dict):
        raise SeasonValidationError("markedDays skal være et objekt")

    start, end = season_bounds(normalized_season)
    normalized: Dict[str, Dict[str, str]] = {}
    for raw_key, raw_value in markings.items():
        parsed = parse_calendar_date_key(str(raw_key))
        if parsed < start or parsed > end:
            raise SeasonValidationError(
                f"Kalenderdatoen {parsed.isoformat()} ligger uden for sæsonen {normalized_season}"
            )
        key = parsed.isoformat()
        if key in normalized:
            raise SeasonValidationError(f"Kalenderen indeholder datoen {key} mere end én gang")
        normalized[key] = normalize_calendar_entry(raw_value)

    if require_complete:
        expected = {item.isoformat() for item in season_dates(normalized_season)}
        missing = sorted(expected - set(normalized))
        if missing:
            raise SeasonValidationError(
                f"Kalenderen mangler {len(missing)} datoer i sæsonen {normalized_season}"
            )
    return normalized


def build_season_calendar(
    season: str,
    day_times: Any,
) -> Dict[str, Dict[str, str]]:
    normalized_times = normalize_day_times(day_times)
    return {
        item.isoformat(): calendar_entry_for_standard(normalized_times[day_key_for_date(item)])
        for item in season_dates(season)
    }


def complete_season_calendar(
    markings: Any,
    season: str,
    day_times: Any,
) -> tuple[Dict[str, Dict[str, str]], int]:
    expected = build_season_calendar(season, day_times)
    if markings is None:
        return expected, len(expected)
    normalized = validate_and_normalize_markings(markings, season, require_complete=False)
    missing_count = 0
    for key, value in expected.items():
        if key not in normalized:
            normalized[key] = value
            missing_count += 1
    return normalized, missing_count


def calendar_entry_is_on(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if is_off_day(entry):
        return False
    status = str(entry.get("status") or "").strip().lower()
    if status in {"on", "open", "active", "tændt", "true", "1", "ja", "yes"}:
        return True
    return bool(entry.get("onTime") or entry.get("offTime"))


def entry_matches_standard(entry: Dict[str, Any], standard: Dict[str, str]) -> bool:
    if is_off_day(standard):
        return not calendar_entry_is_on(entry)
    if not calendar_entry_is_on(entry):
        return False
    entry_on = str(entry.get("onTime") or "").strip()
    entry_off = str(entry.get("offTime") or "").strip()
    if not entry_on and not entry_off:
        return True
    return (
        entry_on == str(standard.get("onTime") or "").strip()
        and entry_off == str(standard.get("offTime") or "").strip()
    )


def apply_standard_times_to_existing_markings(
    markings: Dict[str, Any],
    *,
    old_times: Any,
    new_times: Any,
    preserve_manual_times: bool = True,
) -> tuple[Dict[str, Dict[str, str]], int, int]:
    normalized_old = normalize_day_times(old_times)
    normalized_new = normalize_day_times(new_times)
    updated: Dict[str, Dict[str, str]] = {}
    changed_count = 0
    preserved_manual_count = 0

    for key, value in (markings or {}).items():
        parsed = parse_calendar_date_key(str(key))
        entry = normalize_calendar_entry(value)
        day_key = day_key_for_date(parsed)
        old_standard = normalized_old[day_key]
        new_standard = normalized_new[day_key]

        if preserve_manual_times and not entry_matches_standard(entry, old_standard):
            preserved_manual_count += 1
            updated[parsed.isoformat()] = entry
            continue

        next_entry = calendar_entry_for_standard(new_standard)
        if entry != next_entry:
            changed_count += 1
        updated[parsed.isoformat()] = next_entry

    return updated, changed_count, preserved_manual_count


def apply_standard_times_to_season_calendar(
    markings: Any,
    *,
    season: str,
    old_times: Any,
    new_times: Any,
) -> tuple[Dict[str, Dict[str, str]], int, int, int]:
    """Safely apply new standards to a complete season calendar.

    Missing dates are first reconstructed from the previous standard. Existing
    dates that differ from the previous standard are treated as manual
    deviations and preserved.
    """
    completed, filled_count = complete_season_calendar(markings, season, old_times)
    updated, changed_count, preserved_manual_count = apply_standard_times_to_existing_markings(
        completed,
        old_times=old_times,
        new_times=new_times,
        preserve_manual_times=True,
    )
    return updated, changed_count, preserved_manual_count, filled_count


def effective_organization_times(
    session,
    organization_id: Optional[int],
    season: str,
) -> Dict[str, Dict[str, str]]:
    normalized_season = validate_season(season)
    organization = session.get(Organization, organization_id) if organization_id else None
    if organization is not None:
        season_times = session.exec(
            select(OrganizationSeasonTimes).where(
                OrganizationSeasonTimes.organization_id == organization.id,
                OrganizationSeasonTimes.season == normalized_season,
            )
        ).first()
        if season_times is not None:
            return normalize_day_times(season_times.day_times)
        return normalize_day_times(organization.day_times)
    return copy_system_default_day_times()


def _valid_season_start_or_none(value: Any) -> Optional[int]:
    try:
        return parse_season(str(value))[0]
    except SeasonValidationError:
        return None


def ensure_organization_season_times(
    session,
    organization: Organization,
    seasons: Iterable[str],
) -> tuple[dict[str, OrganizationSeasonTimes], int]:
    requested = [validate_season(item) for item in seasons]
    rows = session.exec(
        select(OrganizationSeasonTimes).where(
            OrganizationSeasonTimes.organization_id == organization.id
        )
    ).all()
    by_season = {row.season: row for row in rows}
    created = 0

    for season in requested:
        if season in by_season:
            continue
        target_start = parse_season(season)[0]
        candidates = [
            row for row in rows
            if (_valid_season_start_or_none(row.season) or 10000) <= target_start
        ]
        source = max(
            candidates,
            key=lambda row: _valid_season_start_or_none(row.season) or -1,
            default=None,
        )
        source_times = source.day_times if source is not None else organization.day_times
        row = OrganizationSeasonTimes(
            organization_id=organization.id,
            season=season,
            day_times=normalize_day_times(source_times),
        )
        session.add(row)
        rows.append(row)
        by_season[season] = row
        created += 1

    return {season: by_season[season] for season in requested}, created


def ensure_client_calendar(
    session,
    client: Client,
    season: str,
    day_times: Any,
) -> tuple[CalendarMarking, bool, int]:
    normalized_season = validate_season(season)
    existing = session.exec(
        select(CalendarMarking).where(
            CalendarMarking.client_id == client.id,
            CalendarMarking.season == normalized_season,
        )
    ).first()
    if existing is None:
        existing = CalendarMarking(
            client_id=client.id,
            season=normalized_season,
            markings=build_season_calendar(normalized_season, day_times),
        )
        session.add(existing)
        return existing, True, len(existing.markings or {})

    completed, filled = complete_season_calendar(existing.markings, normalized_season, day_times)
    if filled or completed != (existing.markings or {}):
        existing.markings = completed
        session.add(existing)
    return existing, False, filled


def _acquire_maintenance_lock(session) -> None:
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.exec(
            text("SELECT pg_advisory_xact_lock(:key)").bindparams(
                key=SEASON_MAINTENANCE_LOCK_KEY
            )
        )


def maintain_current_and_next_seasons(
    session,
    value: Optional[datetime | date] = None,
) -> Dict[str, Any]:
    """Ensure current/next seasons and delete all data older than current.

    The caller owns commit/rollback. The function is idempotent and takes a
    PostgreSQL transaction advisory lock so multiple app workers cannot create
    duplicate rows during rollover.
    """
    _acquire_maintenance_lock(session)
    current, next_season = current_and_next_seasons(value)
    active_seasons = (current, next_season)
    current_start = parse_season(current)[0]

    organizations = session.exec(select(Organization)).all()
    season_rows_by_org: dict[int, dict[str, OrganizationSeasonTimes]] = {}
    created_season_rows = 0
    for organization in organizations:
        rows, created = ensure_organization_season_times(session, organization, active_seasons)
        season_rows_by_org[int(organization.id)] = rows
        created_season_rows += created
    session.flush()

    clients = session.exec(
        select(Client).where(
            Client.status == "approved",
            Client.deleted_at == None,  # noqa: E711 - SQLModel expression
        )
    ).all()
    created_calendars = 0
    filled_calendar_days = 0
    for client in clients:
        org_rows = season_rows_by_org.get(int(client.organization_id)) if client.organization_id else None
        for season in active_seasons:
            if org_rows and season in org_rows:
                day_times = org_rows[season].day_times
            else:
                day_times = effective_organization_times(session, client.organization_id, season)
            _calendar, created, filled = ensure_client_calendar(session, client, season, day_times)
            created_calendars += int(created)
            filled_calendar_days += filled if not created else 0
    session.flush()

    calendar_seasons = set(session.exec(select(CalendarMarking.season)).all())
    organization_seasons = set(session.exec(select(OrganizationSeasonTimes.season)).all())
    old_calendar_seasons = sorted(
        season for season in calendar_seasons
        if (_valid_season_start_or_none(season) is not None)
        and int(_valid_season_start_or_none(season)) < current_start
    )
    old_organization_seasons = sorted(
        season for season in organization_seasons
        if (_valid_season_start_or_none(season) is not None)
        and int(_valid_season_start_or_none(season)) < current_start
    )
    if old_calendar_seasons:
        session.exec(delete(CalendarMarking).where(CalendarMarking.season.in_(old_calendar_seasons)))
    if old_organization_seasons:
        session.exec(
            delete(OrganizationSeasonTimes).where(
                OrganizationSeasonTimes.season.in_(old_organization_seasons)
            )
        )

    return {
        "current_season": current,
        "next_season": next_season,
        "created_organization_seasons": created_season_rows,
        "created_client_calendars": created_calendars,
        "filled_calendar_days": filled_calendar_days,
        "deleted_calendar_seasons": old_calendar_seasons,
        "deleted_organization_seasons": old_organization_seasons,
        "timezone": DK_TIMEZONE_NAME,
    }
