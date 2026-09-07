"""Establish the automatic current/next season contract.

Revision ID: 20260714_37a_season_contract
Revises: 20260714_36a_clientflow_catalog
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from alembic import context, op
import sqlalchemy as sa

revision = "20260714_37a_season_contract"
down_revision = "20260714_36a_clientflow_catalog"
branch_labels = None
depends_on = None

DAY_KEYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)
OLD_DEFAULTS = {
    "monday": {"status": "on", "onTime": "09:00", "offTime": "22:30"},
    "tuesday": {"status": "on", "onTime": "09:00", "offTime": "22:30"},
    "wednesday": {"status": "on", "onTime": "09:00", "offTime": "22:30"},
    "thursday": {"status": "on", "onTime": "09:00", "offTime": "22:30"},
    "friday": {"status": "on", "onTime": "09:00", "offTime": "22:30"},
    "saturday": {"status": "on", "onTime": "08:00", "offTime": "18:00"},
    "sunday": {"status": "on", "onTime": "08:00", "offTime": "18:00"},
}
NEW_DEFAULTS = {
    "monday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "tuesday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "wednesday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "thursday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "friday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "saturday": {"status": "off"},
    "sunday": {"status": "off"},
}
OFF_STATUSES = {"off", "closed", "lukket", "slukket", "false", "0", "nej", "no"}
SEASON_RE = re.compile(r"^(\d{4})/(\d{4})$")

NEW_DEFAULT_SQL = sa.text(
    "jsonb_build_object("
    "'monday', jsonb_build_object('status', 'on', 'onTime', '09:00', 'offTime', '20:00'), "
    "'tuesday', jsonb_build_object('status', 'on', 'onTime', '09:00', 'offTime', '20:00'), "
    "'wednesday', jsonb_build_object('status', 'on', 'onTime', '09:00', 'offTime', '20:00'), "
    "'thursday', jsonb_build_object('status', 'on', 'onTime', '09:00', 'offTime', '20:00'), "
    "'friday', jsonb_build_object('status', 'on', 'onTime', '09:00', 'offTime', '20:00'), "
    "'saturday', jsonb_build_object('status', 'off'), "
    "'sunday', jsonb_build_object('status', 'off'))"
)

OLD_DEFAULT_SQL = sa.text(
    "jsonb_build_object("
    "'monday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), "
    "'tuesday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), "
    "'wednesday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), "
    "'thursday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), "
    "'friday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), "
    "'saturday', jsonb_build_object('onTime', '08:00', 'offTime', '18:00'), "
    "'sunday', jsonb_build_object('onTime', '08:00', 'offTime', '18:00'))"
)


def _season_start(value: str) -> int:
    match = SEASON_RE.fullmatch(str(value or ""))
    if not match:
        raise RuntimeError(f"Ugyldig sæson i databasen: {value!r}")
    start, end = int(match.group(1)), int(match.group(2))
    if end != start + 1 or start < 1900 or end > 9999:
        raise RuntimeError(f"Ugyldig sæson i databasen: {value!r}")
    return start


def _is_off(value) -> bool:
    if not isinstance(value, dict):
        return False
    status = str(value.get("status") or value.get("state") or "on").strip().lower()
    return status in OFF_STATUSES or value.get("enabled") is False


def _normalize_times(value) -> dict:
    source = value if isinstance(value, dict) else {}
    normalized = {}
    for key in DAY_KEYS:
        fallback = OLD_DEFAULTS[key]
        raw = source.get(key)
        if not isinstance(raw, dict):
            raw = fallback
        if _is_off(raw):
            normalized[key] = {"status": "off"}
        else:
            normalized[key] = {
                "status": "on",
                "onTime": str(raw.get("onTime") or fallback["onTime"]),
                "offTime": str(raw.get("offTime") or fallback["offTime"]),
            }
    return normalized


def _calendar_date(key: str) -> date:
    raw = str(key or "")
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Ugyldig kalenderdato i databasen: {raw!r}") from exc


def _entry_is_on(entry) -> bool:
    if not isinstance(entry, dict) or _is_off(entry):
        return False
    status = str(entry.get("status") or "").strip().lower()
    return status in {"on", "open", "active", "tændt", "true", "1", "ja", "yes"} or bool(
        entry.get("onTime") or entry.get("offTime")
    )


def _entry_matches(entry: dict, standard: dict) -> bool:
    if _is_off(standard):
        return not _entry_is_on(entry)
    if not _entry_is_on(entry):
        return False
    entry_on = str(entry.get("onTime") or "").strip()
    entry_off = str(entry.get("offTime") or "").strip()
    if not entry_on and not entry_off:
        return True
    return entry_on == standard["onTime"] and entry_off == standard["offTime"]


def _entry_for(standard: dict) -> dict:
    if _is_off(standard):
        return {"status": "off"}
    return {
        "status": "on",
        "onTime": standard["onTime"],
        "offTime": standard["offTime"],
    }


def _transition_calendar(markings, season: str, old_times: dict, new_times: dict) -> dict:
    if markings is None:
        return {}
    if not isinstance(markings, dict):
        raise RuntimeError("calendarmarking.markings skal være et JSON-objekt")
    start_year = _season_start(season)
    start_date = date(start_year, 8, 1)
    end_date = date(start_year + 1, 7, 31)
    updated = {}
    for key, raw_entry in markings.items():
        item_date = _calendar_date(str(key))
        if item_date < start_date or item_date > end_date:
            raise RuntimeError(
                f"Kalenderdato {item_date.isoformat()} ligger uden for sæson {season}"
            )
        if not isinstance(raw_entry, dict):
            raise RuntimeError(
                f"Kalenderdato {item_date.isoformat()} har ugyldige data"
            )
        day_key = DAY_KEYS[item_date.weekday()]
        entry = dict(raw_entry)
        if _entry_matches(entry, old_times[day_key]):
            entry = _entry_for(new_times[day_key])
        canonical_key = item_date.isoformat()
        if canonical_key in updated:
            raise RuntimeError(
                f"Kalenderen for sæson {season} indeholder datoen {canonical_key} flere gange"
            )
        updated[canonical_key] = entry
    return updated


def _json_param(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _apply_schema_contract() -> None:
    op.alter_column("organization", "day_times", server_default=NEW_DEFAULT_SQL)
    op.alter_column("organizationseasontimes", "day_times", server_default=NEW_DEFAULT_SQL)
    op.create_unique_constraint(
        "calendarmarking_client_season_unique",
        "calendarmarking",
        ["client_id", "season"],
    )


def upgrade() -> None:
    # Offline mode is used by CI to render the migration as SQL. It has no
    # live database connection, so data inspection and conflict detection
    # cannot run there. Emit the schema DDL only; the complete transactional
    # data migration runs during normal online deployment.
    if context.is_offline_mode():
        _apply_schema_contract()
        return

    connection = op.get_bind()

    calendar_rows = connection.execute(sa.text(
        "SELECT id, client_id, season, markings FROM calendarmarking "
        "ORDER BY client_id, season, id"
    )).mappings().all()
    season_rows = connection.execute(sa.text(
        "SELECT id, organization_id, season, day_times FROM organizationseasontimes "
        "ORDER BY organization_id, season, id"
    )).mappings().all()

    # Fail closed on malformed season identifiers before modifying production data.
    for row in calendar_rows:
        _season_start(row["season"])
    for row in season_rows:
        _season_start(row["season"])

    # Merge only byte-semantically identical duplicates. Conflicting calendars
    # require manual review and abort the entire transactional migration.
    grouped = defaultdict(list)
    for row in calendar_rows:
        grouped[(row["client_id"], row["season"])].append(row)
    duplicate_ids_to_delete = []
    for (client_id, season), rows in grouped.items():
        if len(rows) < 2:
            continue
        first = rows[0]["markings"] or {}
        if any((row["markings"] or {}) != first for row in rows[1:]):
            raise RuntimeError(
                "Modstridende calendarmarking-dubletter for "
                f"client_id={client_id}, season={season}; migration afbrudt"
            )
        duplicate_ids_to_delete.extend(row["id"] for row in rows[1:])
    for row_id in duplicate_ids_to_delete:
        connection.execute(
            sa.text("DELETE FROM calendarmarking WHERE id = :id"),
            {"id": row_id},
        )

    organizations = {
        row["id"]: row
        for row in connection.execute(sa.text(
            "SELECT id, day_times FROM organization ORDER BY id"
        )).mappings().all()
    }
    season_times_by_key = {
        (row["organization_id"], row["season"]): row
        for row in season_rows
    }
    clients = {
        row["id"]: row
        for row in connection.execute(sa.text(
            "SELECT id, organization_id FROM client ORDER BY id"
        )).mappings().all()
    }

    local_today = datetime.now(ZoneInfo("Europe/Copenhagen")).date()
    current_start = local_today.year if local_today.month >= 8 else local_today.year - 1

    # Safely transition existing standard-following client days. Manual
    # deviations, holidays and explicitly switched-off days remain unchanged.
    remaining_rows = connection.execute(sa.text(
        "SELECT id, client_id, season, markings FROM calendarmarking ORDER BY id"
    )).mappings().all()
    for row in remaining_rows:
        if _season_start(row["season"]) < current_start:
            continue
        client = clients.get(row["client_id"])
        organization_id = client["organization_id"] if client else None
        season_source = season_times_by_key.get((organization_id, row["season"]))
        organization_source = organizations.get(organization_id)
        raw_times = (
            season_source["day_times"] if season_source is not None
            else organization_source["day_times"] if organization_source is not None
            else OLD_DEFAULTS
        )
        old_times = _normalize_times(raw_times)
        new_times = NEW_DEFAULTS if old_times == OLD_DEFAULTS else old_times
        transitioned = _transition_calendar(row["markings"], row["season"], old_times, new_times)
        if transitioned != (row["markings"] or {}):
            connection.execute(
                sa.text(
                    "UPDATE calendarmarking SET markings = CAST(:markings AS jsonb) WHERE id = :id"
                ),
                {"id": row["id"], "markings": _json_param(transitioned)},
            )

    for organization_id, row in organizations.items():
        normalized = _normalize_times(row["day_times"])
        if normalized == OLD_DEFAULTS:
            connection.execute(
                sa.text(
                    "UPDATE organization SET day_times = CAST(:day_times AS jsonb) WHERE id = :id"
                ),
                {"id": organization_id, "day_times": _json_param(NEW_DEFAULTS)},
            )

    for row in season_rows:
        normalized = _normalize_times(row["day_times"])
        if normalized == OLD_DEFAULTS:
            connection.execute(
                sa.text(
                    "UPDATE organizationseasontimes "
                    "SET day_times = CAST(:day_times AS jsonb) WHERE id = :id"
                ),
                {"id": row["id"], "day_times": _json_param(NEW_DEFAULTS)},
            )

    # Once rollover is safe, all data for passed seasons is removed.
    for row in remaining_rows:
        if _season_start(row["season"]) < current_start:
            connection.execute(
                sa.text("DELETE FROM calendarmarking WHERE id = :id"),
                {"id": row["id"]},
            )
    for row in season_rows:
        if _season_start(row["season"]) < current_start:
            connection.execute(
                sa.text("DELETE FROM organizationseasontimes WHERE id = :id"),
                {"id": row["id"]},
            )

    _apply_schema_contract()


def downgrade() -> None:
    # Deleted passed-season data and migrated user data are intentionally not
    # reconstructed. The schema-level contract can still be rolled back.
    op.drop_constraint(
        "calendarmarking_client_season_unique",
        "calendarmarking",
        type_="unique",
    )
    op.alter_column("organizationseasontimes", "day_times", server_default=OLD_DEFAULT_SQL)
    op.alter_column("organization", "day_times", server_default=OLD_DEFAULT_SQL)
