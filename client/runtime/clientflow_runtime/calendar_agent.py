"""Local Calendar scheduler for canonical Display power/browser transitions."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

from .atomic import atomic_write_json
from .config import DomainCredential
from .constants import Domain
from .display_local_control import (
    calendar_manual_override_created_at,
    clear_calendar_manual_override,
    display_control_lock,
    runtime_action,
    set_display_power,
)
from .logging_utils import configure_logging
from .net import DomainTransport, TransportError, backoff_seconds
from .unix_rpc import RpcError

STATE_DIR = Path(os.getenv("CLIENTFLOW_CALENDAR_STATE_DIR", "/var/lib/clientflow/calendar"))
CACHE_PATH = STATE_DIR / "schedule.json"
STATUS_PATH = STATE_DIR / "status.json"
POLL_SECONDS = max(15.0, float(os.getenv("CLIENTFLOW_CALENDAR_POLL_SECONDS", "60")))
EVALUATE_SECONDS = max(0.5, float(os.getenv("CLIENTFLOW_CALENDAR_EVALUATE_SECONDS", "1")))
RECONCILE_SECONDS = max(5.0, float(os.getenv("CLIENTFLOW_CALENDAR_RECONCILE_SECONDS", "30")))
SCHEMA_VERSION = 1


class CalendarPlanError(RuntimeError):
    pass


def _canonical_revision(seasons: dict[str, Any]) -> str:
    encoded = json.dumps(
        seasons,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_hhmm(value: Any) -> tuple[int, int]:
    raw = str(value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise CalendarPlanError("Kalendertid skal være HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise CalendarPlanError("Kalendertid er uden for gyldigt interval")
    return hour, minute


def _normalize_entry(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise CalendarPlanError("Kalenderdag skal være et objekt")
    status = str(value.get("status") or "").strip().lower()
    if status == "off":
        return {"status": "off"}
    if status != "on":
        raise CalendarPlanError("Kalenderdagens status skal være on eller off")
    on_time = str(value.get("onTime") or "").strip()
    off_time = str(value.get("offTime") or "").strip()
    on_parts = _parse_hhmm(on_time)
    off_parts = _parse_hhmm(off_time)
    if on_parts > off_parts:
        raise CalendarPlanError("Tænd-tid skal være før sluk-tid")
    return {"status": "on", "onTime": on_time, "offTime": off_time}


def _validate_plan(payload: dict[str, Any], *, client_id: int) -> dict[str, Any]:
    if int(payload.get("schema_version") or 0) != SCHEMA_VERSION:
        raise CalendarPlanError("Calendar schema_version understøttes ikke")
    if int(payload.get("client_id") or 0) != client_id:
        raise CalendarPlanError("Calendar payload er bundet til en anden klient")
    seasons_raw = payload.get("seasons")
    if not isinstance(seasons_raw, dict) or not seasons_raw:
        raise CalendarPlanError("Calendar payload mangler sæsoner")
    seasons: dict[str, dict[str, dict[str, str]]] = {}
    for season, days_raw in seasons_raw.items():
        if not isinstance(season, str) or not isinstance(days_raw, dict):
            raise CalendarPlanError("Calendar sæsonformat er ugyldigt")
        days: dict[str, dict[str, str]] = {}
        for raw_date, entry in days_raw.items():
            date_key = str(raw_date)[:10]
            try:
                datetime.strptime(date_key, "%Y-%m-%d")
            except ValueError as exc:
                raise CalendarPlanError("Calendar indeholder ugyldig dato") from exc
            days[date_key] = _normalize_entry(entry)
        seasons[season] = days
    revision = str(payload.get("revision") or "").strip().lower()
    if not revision or revision != _canonical_revision(seasons):
        raise CalendarPlanError("Calendar revision matcher ikke payload")
    return {
        "schema_version": SCHEMA_VERSION,
        "client_id": client_id,
        "revision": revision,
        "seasons": seasons,
    }


def _read_cache(*, client_id: int) -> dict[str, Any] | None:
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return _validate_plan(raw, client_id=client_id)
    except (CalendarPlanError, TypeError, ValueError):
        return None


def _fetch_plan(transport: DomainTransport) -> dict[str, Any]:
    client_id = transport.credential.client_id
    payload = transport.json_request(
        "GET",
        f"/api/display-agent/clients/{client_id}/calendar",
    )
    plan = _validate_plan(payload, client_id=client_id)
    atomic_write_json(CACHE_PATH, plan, mode=0o600)
    return plan


def _entry_for_today(plan: dict[str, Any], now: datetime) -> dict[str, str]:
    today = now.date().isoformat()
    for days in plan.get("seasons", {}).values():
        if today in days:
            return dict(days[today])
    raise CalendarPlanError(f"Calendar cache mangler dato {today}")


def _desired_state(plan: dict[str, Any], now: datetime) -> str:
    entry = _entry_for_today(plan, now)
    if entry.get("status") == "off":
        return "off"
    on_hour, on_minute = _parse_hhmm(entry.get("onTime"))
    off_hour, off_minute = _parse_hhmm(entry.get("offTime"))
    start = now.replace(hour=on_hour, minute=on_minute, second=0, microsecond=0)
    end = now.replace(hour=off_hour, minute=off_minute, second=0, microsecond=0)
    return "on" if start <= now < end else "off"




def _calendar_boundary_since(plan: dict[str, Any], since: datetime, now: datetime) -> bool:
    """Return true when an ON/OFF wall-clock boundary occurred after ``since``.

    This makes a manual Display override survive a Calendar service restart but
    never longer than the next actual schedule boundary in the current boot.
    """
    if since >= now:
        return False
    day = since.date()
    end_day = now.date()
    while day <= end_day:
        date_key = day.isoformat()
        entry: dict[str, str] | None = None
        for days in plan.get("seasons", {}).values():
            if date_key in days:
                entry = dict(days[date_key])
                break
        if entry and entry.get("status") == "on":
            on_hour, on_minute = _parse_hhmm(entry.get("onTime"))
            off_hour, off_minute = _parse_hhmm(entry.get("offTime"))
            if (on_hour, on_minute) < (off_hour, off_minute):
                for hour, minute in ((on_hour, on_minute), (off_hour, off_minute)):
                    boundary = datetime(
                        day.year,
                        day.month,
                        day.day,
                        hour,
                        minute,
                        tzinfo=now.tzinfo,
                    )
                    if since < boundary <= now:
                        return True
        day += timedelta(days=1)
    return False


def _should_enforce(
    *,
    manual_override: bool,
    last_schedule_state: str | None,
    desired: str,
    last_enforce_at: float,
    now_mono: float,
) -> bool:
    if manual_override:
        return False
    return (
        last_schedule_state is None
        or desired != last_schedule_state
        or (now_mono - last_enforce_at) >= RECONCILE_SECONDS
    )


def _apply_transition(state: str) -> None:
    with display_control_lock():
        if state == "on":
            set_display_power("on")
            runtime_action("start_browser")
            return
        if state == "off":
            runtime_action("stop_browser")
            set_display_power("off")
            return
    raise CalendarPlanError("Ukendt calendar desired state")


def _timezone_label(now: datetime) -> str:
    zone = now.astimezone().tzinfo
    return str(zone) if zone is not None else "unknown"


def _write_status(
    *,
    state: str,
    plan: dict[str, Any] | None,
    desired: str | None,
    last_fetch_at: float | None,
    last_transition_at: float | None,
    error: str | None,
    manual_override: bool = False,
) -> None:
    now = datetime.now().astimezone()
    atomic_write_json(
        STATUS_PATH,
        {
            "schema_version": 1,
            "state": state,
            "schedule_state": desired or "unknown",
            "calendar_revision": plan.get("revision") if plan else None,
            "local_timezone": _timezone_label(now),
            "last_fetch_at": last_fetch_at,
            "last_transition_at": last_transition_at,
            "updated_at": time.time(),
            "manual_override": bool(manual_override),
            "error": (error or "")[:500] or None,
        },
        mode=0o600,
    )


def main() -> int:
    logger = configure_logging("clientflow.calendar")
    credential = DomainCredential.load(Domain.DISPLAY)
    transport = DomainTransport(credential)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    plan = _read_cache(client_id=credential.client_id)
    last_fetch_at: float | None = None
    last_transition_at: float | None = None
    last_schedule_state: str | None = None
    last_enforce_at = 0.0
    next_fetch = 0.0
    fetch_attempt = 0

    while True:
        now_mono = time.monotonic()
        error: str | None = None
        try:
            if now_mono >= next_fetch:
                try:
                    plan = _fetch_plan(transport)
                    last_fetch_at = time.time()
                    fetch_attempt = 0
                    next_fetch = now_mono + POLL_SECONDS
                except (TransportError, CalendarPlanError, TypeError, ValueError) as exc:
                    error = f"calendar_fetch_failed: {exc}"
                    logger.warning("calendar_fetch_failed", extra={"event": "calendar_fetch_failed"})
                    next_fetch = now_mono + backoff_seconds(fetch_attempt)
                    fetch_attempt += 1

            if plan is None:
                _write_status(
                    state="degraded",
                    plan=None,
                    desired=None,
                    last_fetch_at=last_fetch_at,
                    last_transition_at=last_transition_at,
                    error=error or "Ingen gyldig cached calendar",
                )
                time.sleep(EVALUATE_SECONDS)
                continue

            now_local = datetime.now().astimezone()
            desired = _desired_state(plan, now_local)
            override_created_at = calendar_manual_override_created_at()
            manual_override = override_created_at is not None
            if manual_override:
                override_local = datetime.fromtimestamp(override_created_at).astimezone()
                if _calendar_boundary_since(plan, override_local, now_local):
                    clear_calendar_manual_override()
                    manual_override = False
            now_mono = time.monotonic()
            should_enforce = _should_enforce(
                manual_override=manual_override,
                last_schedule_state=last_schedule_state,
                desired=desired,
                last_enforce_at=last_enforce_at,
                now_mono=now_mono,
            )
            if should_enforce:
                try:
                    _apply_transition(desired)
                except (RpcError, OSError, RuntimeError, ValueError) as exc:
                    error = f"calendar_transition_failed: {exc}"
                    _write_status(
                        state="degraded",
                        plan=plan,
                        desired=desired,
                        last_fetch_at=last_fetch_at,
                        last_transition_at=last_transition_at,
                        error=error,
                        manual_override=manual_override,
                    )
                    logger.exception("calendar_transition_failed", extra={"event": desired})
                    time.sleep(max(1.0, EVALUATE_SECONDS))
                    continue
                last_transition_at = time.time()
                last_enforce_at = time.monotonic()
                logger.info("calendar_transition_applied", extra={"event": desired})
            last_schedule_state = desired

            _write_status(
                state="running",
                plan=plan,
                desired=desired,
                last_fetch_at=last_fetch_at,
                last_transition_at=last_transition_at,
                error=error,
                manual_override=manual_override,
            )
            time.sleep(EVALUATE_SECONDS)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            logger.exception("calendar_loop_failed")
            _write_status(
                state="degraded",
                plan=plan,
                desired=last_schedule_state,
                last_fetch_at=last_fetch_at,
                last_transition_at=last_transition_at,
                error=f"calendar_loop_failed: {exc}",
            )
            time.sleep(2.0)
