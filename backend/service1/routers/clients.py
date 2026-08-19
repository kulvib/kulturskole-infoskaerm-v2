import logging

from fastapi import APIRouter, Depends, HTTPException, Body, Request
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import select, delete
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from ..db import get_session
from ..audit import add_audit_log
from ..models import Client, ClientRead, ClientCreate, ClientUpdate, CalendarMarking, ChromeAction, Organization, EnrollmentToken
from ..auth import get_current_user, get_current_admin_user, get_current_superadmin_user, get_current_user_or_client, require_client_self_or_user, principal_is_client, get_password_hash, validate_password_strength
from ..models import utcnow
from ..observability import log_safe_exception
from ..lifecycle import prepare_client_for_permanent_delete
from ..livestream_v2 import request_start as request_livestream_v2_start, request_stop as request_livestream_v2_stop
from ..terminal_v2_models import TerminalClient, TerminalCredential
from ..remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from ..season_service import (
    SeasonValidationError,
    apply_standard_times_to_existing_markings,
    build_season_calendar,
    current_and_next_seasons,
    current_season,
    effective_organization_times,
    ensure_client_calendar,
    validate_supported_season,
)
from ..clientflow_releases import (
    ClientFlowCatalogError, compare_versions, load_catalog, resolve_release,
    validate_release_compatibility,
)
import os
import secrets
import re

logger = logging.getLogger(__name__)

router = APIRouter()

# Brug samme timeout alle steder i backend. 15 sek. kan give meget hurtige
# offline/online-skift, især omkring reboot. Sæt env til 15 hvis du vil bevare
# den gamle adfærd.
ONLINE_TIMEOUT_SECONDS = int(os.getenv("CLIENTFLOW_ONLINE_TIMEOUT_SECONDS", "120"))

VALID_CLIENT_STATES = {"normal", "sleeping", "wakeup", "shutdown", "error", "updating", "rebooting"}
BROWSER_REFRESH_DEFAULT_SECONDS = int(os.getenv("CLIENTFLOW_BROWSER_REFRESH_DEFAULT_SECONDS", "900"))
BROWSER_REFRESH_MIN_SECONDS = int(os.getenv("CLIENTFLOW_BROWSER_REFRESH_MIN_SECONDS", "60"))
BROWSER_REFRESH_MAX_SECONDS = int(os.getenv("CLIENTFLOW_BROWSER_REFRESH_MAX_SECONDS", "86400"))

CLIENTFLOW_UPDATE_TERMINAL_STATUSES = {"ready", "success", "up_to_date", "error"}
CLIENTFLOW_UPDATE_BUSY_STATUSES = {
    "requested", "starting", "preparing", "fetching_manifest",
    "downloading", "verifying", "installing", "stopping_services",
}
CLIENTFLOW_STALE_UPDATE_SECONDS = int(os.getenv("CLIENTFLOW_STALE_UPDATE_SECONDS", "1800"))
OS_UPDATE_STALE_SECONDS = int(os.getenv("CLIENTFLOW_OS_UPDATE_STALE_SECONDS", "3600"))
UBUNTU_UPDATE_STATUSES = {
    "ready", "requested", "starting", "checking", "installing", "cleanup",
    "rebooting", "success", "up_to_date", "error",
}
UBUNTU_UPDATE_FIELDS = {
    "ubuntu_update_status", "ubuntu_update_step", "ubuntu_update_message",
    "ubuntu_update_error", "ubuntu_update_started_at", "ubuntu_update_updated_at",
    "ubuntu_update_finished_at", "ubuntu_update_progress",
    "ubuntu_update_package_count", "ubuntu_update_reboot_required",
}
VALID_PENDING_CHROME_ACTION_SOURCES = {"actionbutton", "calendar", "viewer_heartbeat_timeout", "viewer_inactivity_timeout", "viewer_left_control_room", "control_room_back", "livestream_watchdog", "system", "api", "client", "self_update"}

BLOCKING_ACTIONS = {"start", "stop", "sleep", "wakeup", "restart", "shutdown", "reset_browser"}

# Backend-side guardrails for UI actions. Frontend also disables buttons,
# but backend must be authoritative so direct API calls cannot start the
# kiosk browser while the client is in display sleep.
KIOSK_BROWSER_ACTIONS = {"start", "stop", "reset_browser"}
DISPLAY_ONLY_ACTIONS = {"wakeup"}
DISPLAY_SLEEP_ACTIONS = {"sleep"}
ACTIONS_ALLOWED_WHILE_SLEEPING = {"wakeup", "none"}

DISPLAY_RESOLUTION_PRESETS = {
    "auto": (None, None),
    "hd_720p": (1280, 720),
    "hd_ready": (1366, 768),
    "hd_plus": (1600, 900),
    "full_hd": (1920, 1080),
    "qhd_1440p": (2560, 1440),
    "uhd_4k": (3840, 2160),
    "wxga": (1280, 800),
    "wuxga": (1920, 1200),
    "wqxga": (2560, 1600),
    "ultrawide_fhd": (2560, 1080),
    "ultrawide_qhd": (3440, 1440),
    "super_ultrawide": (5120, 1440),
    "signage_wide": (3840, 1080),
    "hd_portrait": (720, 1280),
    "hd_ready_portrait": (768, 1366),
    "full_hd_portrait": (1080, 1920),
    "qhd_portrait": (1440, 2560),
    "uhd_4k_portrait": (2160, 3840),
    "custom": (None, None),
}

DISPLAY_RESOLUTION_DESIRED_FIELDS = {
    "display_resolution_preset",
    "display_resolution_mode",
    "display_resolution_width",
    "display_resolution_height",
    "display_resolution_refresh_rate",
    "display_resolution_rotation",
}

DISPLAY_RESOLUTION_ACTION_FIELDS = {
    "display_resolution_action",
}

DESKTOP_LOCKDOWN_DESIRED_FIELDS = {
    "desktop_lockdown_enabled",
}

DESKTOP_LOCKDOWN_CLIENT_REPORT_FIELDS = {
    "desktop_lockdown_status",
    "desktop_lockdown_message",
    "desktop_lockdown_last_applied_at",
}

VALID_DESKTOP_LOCKDOWN_STATUSES = {
    "unknown",
    "pending",
    "applying",
    "applied",
    "rolling_back",
    "disabled",
    "error",
}

VALID_DISPLAY_RESOLUTION_ACTIONS = {"detect", "apply"}

DISPLAY_RESOLUTION_CLIENT_REPORT_FIELDS = {
    "display_resolution_current_output",
    "display_resolution_current_width",
    "display_resolution_current_height",
    "display_resolution_current_refresh_rate",
    "display_resolution_status",
    "display_resolution_error",
    "display_resolution_last_applied_at",
    "display_detected_outputs",
    "display_detected_updated_at",
}

VALID_DISPLAY_RESOLUTION_MODES = {"auto", "fixed"}
VALID_DISPLAY_ROTATIONS = {"normal", "left", "right", "inverted"}
VALID_DISPLAY_STATUSES = {"unknown", "pending", "detected", "applying", "applied", "error"}

LOCAL_MANAGEMENT_ACTIONS = {"cfadmin_password", "hostname"}
VALID_LOCAL_MANAGEMENT_STATUSES = {"ready", "pending", "running", "success", "error"}
LOCAL_MANAGEMENT_BUSY_STATUSES = {"pending", "running"}
LOCAL_MANAGEMENT_TERMINAL_STATUSES = {"ready", "success", "error"}


class LocalCfadminPasswordRequest(BaseModel):
    password: str = PydanticField(..., min_length=1, max_length=256)


class LocalHostnameRequest(BaseModel):
    name: str = PydanticField(..., min_length=1, max_length=253)


class LocalManagementStatusRequest(BaseModel):
    request_id: str
    status: str
    message: Optional[str] = None
    error: Optional[str] = None


class ClientOrganizationChangeRequest(BaseModel):
    organization_id: Optional[int] = None
    season: Optional[str] = None
    apply_organization_standard_times: bool = True
    preserve_manual_times: bool = True


class ClientOrganizationChangeResponse(ClientRead):
    calendar_updated: bool = False
    calendar_changed_days: int = 0
    manual_days_preserved: int = 0
    season: str


class ClientApprovalRequest(BaseModel):
    organization_id: Optional[int] = None


class ClientFlowUpdateRequest(BaseModel):
    target_version: str = PydanticField(default="latest", min_length=1, max_length=40)
    confirm_downgrade: bool = False
    reason: Optional[str] = PydanticField(default=None, max_length=500)


EXPECTED_CLIENT_TIMEZONE = "Europe/Copenhagen"
CLOCK_DRIFT_WARNING_SECONDS = 30.0
CLOCK_DRIFT_CRITICAL_SECONDS = 60.0
DIAGNOSTIC_FIELDS = {
    "diagnostics_updated_at",
    "system_timezone",
    "ntp_enabled",
    "ntp_synchronized",
    "client_time_utc",
    "active_network_type",
    "active_network_interface",
    "active_network_ip",
    "active_network_mac",
    "service_clientflow_status",
    "service_calendar_status",
    "service_browser_guard_status",
    "service_remote_terminal_status",
    "service_admin_terminal_status",
    "service_remote_desktop_status",
    "service_kiosk_x11_guard_status",  # legacy/optional; kept for backward compatibility
    "service_livestream_status",
    "service_selfupdate_status",
    "service_ubuntu_update_status",
    "service_local_reboot_reporter_status",
    "service_local_shutdown_reporter_status",
    "livestream_process_status",
}

POWER_LIFECYCLE_FIELDS = {
    "last_boot_id",
    "last_boot_at",
    "last_power_event",
    "last_power_event_at",
    "last_power_event_source",
    "last_reboot_started_at",
    "last_shutdown_started_at",
}


def _now_naive_utc() -> datetime:
    return utcnow()


def _normalise_reported_utc(value: object) -> Optional[datetime]:
    if value is None:
        return None
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _apply_time_integrity_report(client: Client, fields: set[str]) -> None:
    """Compute the authoritative clock result at receipt time.

    The client reports its UTC clock, configured timezone and NTP state. The
    backend computes drift against its own UTC clock so a compromised or stale
    client cannot declare itself healthy by sending a fabricated drift/status.
    """
    if not ({
        "system_timezone", "ntp_enabled", "ntp_synchronized", "client_time_utc"
    } & fields):
        return

    reported = _normalise_reported_utc(getattr(client, "client_time_utc", None))
    client.client_time_utc = reported
    timezone_value = str(getattr(client, "system_timezone", None) or "").strip() or None
    client.system_timezone = timezone_value

    drift: Optional[float] = None
    if reported is not None:
        drift = round(abs((utcnow() - reported).total_seconds()), 3)
    client.clock_drift_seconds = drift

    reasons: list[str] = []
    status = "ok"
    if timezone_value != EXPECTED_CLIENT_TIMEZONE:
        status = "critical"
        reasons.append(
            f"Tidszone er {timezone_value or 'ukendt'}; forventet {EXPECTED_CLIENT_TIMEZONE}"
        )
    if client.ntp_enabled is not True:
        if client.ntp_enabled is False:
            status = "critical"
        elif status == "ok":
            status = "warning"
        reasons.append("NTP er deaktiveret" if client.ntp_enabled is False else "NTP-status er ukendt")
    if client.ntp_synchronized is not True:
        if client.ntp_synchronized is False:
            status = "critical"
        elif status == "ok":
            status = "warning"
        reasons.append(
            "Systemuret er ikke NTP-synkroniseret"
            if client.ntp_synchronized is False
            else "NTP-synkronisering er ukendt"
        )
    if drift is None:
        if status == "ok":
            status = "warning"
        reasons.append("Klientens UTC-tid mangler")
    elif drift > CLOCK_DRIFT_CRITICAL_SECONDS:
        status = "critical"
        reasons.append(f"Ur-afvigelse er {drift:.1f} sekunder")
    elif drift > CLOCK_DRIFT_WARNING_SECONDS:
        if status == "ok":
            status = "warning"
        reasons.append(f"Ur-afvigelse er {drift:.1f} sekunder")

    client.time_sync_status = status
    client.time_sync_message = " · ".join(reasons) if reasons else "Tidszone, NTP og systemur er korrekte"


def _principal_power_source(principal) -> str:
    try:
        if principal_is_client(principal):
            return "client"
    except Exception:
        pass
    role = str(getattr(principal, "role", "") or "").strip().lower()
    return "backend" if role else "unknown"


def _normalize_power_event_value(value) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if not raw:
        return None
    aliases = {
        "rebooting": "reboot_started",
        "reboot": "reboot_started",
        "shutdown": "shutdown_started",
        "shutting_down": "shutdown_started",
        "poweroff": "shutdown_started",
        "power_off": "shutdown_started",
        "boot": "boot_completed",
    }
    return aliases.get(raw, raw)[:80]

# Felter som en klient med client-token selv må opdatere på /clients/{id}/update.
# Admin/frontend kan fortsat opdatere alle de eksisterende ClientUpdate-felter.
CLIENT_SELF_UPDATE_FIELDS = {
    "machine_id",
    "ubuntu_version",
    "uptime",
    "wifi_ip_address",
    "wifi_mac_address",
    "lan_ip_address",
    "lan_mac_address",
    "chrome_status",
    "chrome_last_updated",
    "chrome_color",
    "chrome_step",
    "last_seen",
    "pending_reboot",
    "pending_shutdown",
    "pending_chrome_action",
    "pending_chrome_action_source",
    "livestream_desired_state",
    "livestream_stop_reason",
    "state",
    "last_boot_id",
    "last_boot_at",
    "last_power_event",
    "last_power_event_at",
    "last_power_event_source",
    "last_reboot_started_at",
    "last_shutdown_started_at",
    "livestream_status",
    "livestream_last_segment",
    "livestream_last_error",
    "diagnostics_updated_at",
    "system_timezone",
    "ntp_enabled",
    "ntp_synchronized",
    "client_time_utc",
    "active_network_type",
    "active_network_interface",
    "active_network_ip",
    "active_network_mac",
    "service_clientflow_status",
    "service_calendar_status",
    "service_browser_guard_status",
    "service_remote_terminal_status",
    "service_admin_terminal_status",
    "service_remote_desktop_status",
    "service_kiosk_x11_guard_status",  # legacy/optional; kept for backward compatibility
    "service_livestream_status",
    "service_selfupdate_status",
    "service_ubuntu_update_status",
    "service_local_reboot_reporter_status",
    "service_local_shutdown_reporter_status",
    "livestream_process_status",
    "display_resolution_current_output",
    "display_resolution_current_width",
    "display_resolution_current_height",
    "display_resolution_current_refresh_rate",
    "display_resolution_status",
    "display_resolution_error",
    "display_resolution_last_applied_at",
    "display_detected_outputs",
    "display_detected_updated_at",
    "ubuntu_updates_available",
    "pending_os_update",
    "ubuntu_update_status",
    "ubuntu_update_step",
    "ubuntu_update_message",
    "ubuntu_update_error",
    "ubuntu_update_started_at",
    "ubuntu_update_updated_at",
    "ubuntu_update_finished_at",
    "ubuntu_update_progress",
    "ubuntu_update_package_count",
    "ubuntu_update_reboot_required",
    "client_version",
    "client_version_patch",
    "client_version_updated_at",
    "client_update_status",
    "client_update_message",
    "client_update_requested_at",
    "client_update_started_at",
    "client_update_finished_at",
    "client_update_error",
    "client_update_target_version",
    "client_update_deployment_sequence",
    "client_update_applied_deployment_sequence",
    "desktop_lockdown_status",
    "desktop_lockdown_message",
    "desktop_lockdown_last_applied_at",
}


def normalize_client_state(value: str) -> str:
    normalized = str(value).lower()
    if normalized == "sleep":
        return "sleeping"
    return normalized


def _as_naive_utc(dt):
    """
    DB-feltet last_seen/chrome_last_updated kan være naive UTC eller timezone-aware.
    Sammenlign altid som naive UTC, så is_online ikke fejler eller giver forkert resultat.
    """
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _chrome_action_value(value):
    """Returnerer Enum.value når feltet er ChromeAction, ellers string/None."""
    if value is None:
        return None
    return getattr(value, "value", value)


def _normalize_chrome_action_name(action):
    if action is None:
        return None
    value = getattr(action, "value", action)
    return str(value).strip().lower()


def _principal_log_context(user) -> tuple[str, Optional[int], str]:
    try:
        if principal_is_client(user):
            return "client", getattr(user, "id", None), "client"
    except Exception:
        pass
    return "user", getattr(user, "id", None), getattr(user, "role", None) or "unknown"


def _current_update_detail(client: Client) -> str:
    """Giver en mere præcis besked, når klienten allerede er låst af en update."""
    pending_action = _chrome_action_value(getattr(client, "pending_chrome_action", None))
    if pending_action and str(pending_action).lower() != "none":
        return f"Klienten er allerede ved at opdatere ({pending_action})"

    if getattr(client, "pending_os_update", False):
        return "Klienten er allerede ved at opdatere (os_update)"

    client_update_status = str(getattr(client, "client_update_status", "") or "").lower()
    if client_update_status and client_update_status not in CLIENTFLOW_UPDATE_TERMINAL_STATUSES:
        return f"Klienten er allerede ved at opdatere ({client_update_status})"

    return "Klienten er allerede ved at opdatere"


def _client_state_value(client: Client) -> str:
    return normalize_client_state(str(getattr(client, "state", "normal") or "normal").strip().lower())


def _validate_chrome_command_state(client: Client, action: str, current_pca: str):
    """
    Central backend guard for kiosk/display actions.

    Frontend disables buttons for the same cases, but this guard is the
    authoritative protection for direct API calls and stale browser UIs.

    Return a dict for idempotent OK/no-op cases. Raise HTTPException for
    invalid transitions. Return None when action may continue normally.
    """
    action = _normalize_chrome_action_name(action) or ""
    current_pca = _normalize_chrome_action_name(current_pca) or "none"
    state = _client_state_value(client)
    approved = _client_is_approved(client)

    if not action:
        raise HTTPException(status_code=400, detail="Missing action")

    # Wake is display-only. If a stale UI calls wake while the client is already
    # awake, treat it as idempotent success instead of starting Chrome or
    # clearing cookies/browser data.
    if action == "wakeup" and not state.startswith("sleep"):
        if current_pca == "wakeup":
            return {
                "status": "ok",
                "already_requested": True,
                "pending_chrome_action": current_pca,
                "message": "Væk fra dvale er allerede sendt",
            }
        return {
            "status": "ok",
            "already_awake": True,
            "pending_chrome_action": current_pca,
            "message": "Klienten er allerede vågen",
        }

    if state.startswith("sleep"):
        if action == "sleep":
            return {
                "status": "ok",
                "already_sleeping": True,
                "pending_chrome_action": current_pca,
                "message": "Klienten er allerede i dvale",
            }
        if action not in ACTIONS_ALLOWED_WHILE_SLEEPING:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Klienten er i dvale. Brug 'Væk fra dvale' først. "
                    "Wake er display-only og starter ikke kiosk browseren."
                ),
            )

    if action in KIOSK_BROWSER_ACTIONS and not approved:
        raise HTTPException(
            status_code=409,
            detail="Kiosk browser kan kun styres på en godkendt klient",
        )


    return None



def _field_value(client, client_update, fields, name, default=None):
    if name in fields:
        return getattr(client_update, name)
    return getattr(client, name, default)


def _normalize_browser_refresh_interval(value):
    """0 deaktiverer auto-refresh; ellers tillades kun 60s..86400s."""
    if value in (None, ""):
        return BROWSER_REFRESH_DEFAULT_SECONDS
    try:
        seconds = int(value)
    except Exception:
        raise HTTPException(status_code=400, detail="Browser refresh-interval skal være et heltal i sekunder")
    if seconds == 0:
        return 0
    if seconds < BROWSER_REFRESH_MIN_SECONDS or seconds > BROWSER_REFRESH_MAX_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Browser refresh-interval skal være 0 eller mellem {BROWSER_REFRESH_MIN_SECONDS} og {BROWSER_REFRESH_MAX_SECONDS} sekunder",
        )
    return seconds


def _normalize_client_name(value) -> str:
    name = str(value or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Klientnavn må ikke være tomt")
    if len(name) > 255:
        raise HTTPException(status_code=400, detail="Klientnavn er for langt")
    return name


def _normalize_linux_hostname(value) -> str:
    hostname = str(value or "").strip()
    if not hostname:
        raise HTTPException(status_code=400, detail="Lokalt hostname må ikke være tomt")
    if len(hostname) > 253:
        raise HTTPException(status_code=400, detail="Lokalt hostname er for langt")
    if hostname.endswith("."):
        hostname = hostname[:-1]
    labels = hostname.split(".")
    if not labels or any(not label for label in labels):
        raise HTTPException(status_code=400, detail="Lokalt hostname har ugyldigt format")
    for label in labels:
        if len(label) > 63:
            raise HTTPException(status_code=400, detail="Et hostname-led må højst være 63 tegn")
        if label.startswith("-") or label.endswith("-"):
            raise HTTPException(status_code=400, detail="Hostname-led må ikke starte eller slutte med bindestreg")
        if not re.fullmatch(r"[A-Za-z0-9-]+", label):
            raise HTTPException(status_code=400, detail="Hostname må kun indeholde bogstaver, tal, bindestreg og punktum")
    return hostname.lower()


def _normalize_local_client_display_name(value) -> str:
    name = str(value or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Klientnavn må ikke være tomt")
    if len(name) > 120:
        raise HTTPException(status_code=400, detail="Klientnavn er for langt")
    if any(ch in name for ch in ("\n", "\r", "\x00")):
        raise HTTPException(status_code=400, detail="Klientnavn må ikke indeholde linjeskift")
    return name


def _derive_linux_hostname_from_client_name(value) -> str:
    name = _normalize_local_client_display_name(value)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        raise HTTPException(status_code=400, detail="Klientnavn kan ikke omsættes til hostname")
    return _normalize_linux_hostname(slug[:63].strip("-"))


def _validate_local_password(password: str) -> str:
    value = str(password or "")
    if any(ch in value for ch in ("\n", "\r", "\x00")):
        raise HTTPException(status_code=400, detail="Kodeord må ikke indeholde linjeskift eller nul-tegn")
    validate_password_strength(value)
    return value


def _local_management_payload(client: Client, *, include_secret: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": getattr(client, "local_management_action", None),
        "request_id": getattr(client, "local_management_request_id", None),
        "desired_hostname": getattr(client, "local_management_desired_hostname", None),
        "desired_client_name": getattr(client, "name", None) if getattr(client, "local_management_action", None) == "hostname" else None,
        "status": getattr(client, "local_management_status", None) or "ready",
        "message": getattr(client, "local_management_message", None),
        "requested_at": getattr(client, "local_management_requested_at", None),
        "started_at": getattr(client, "local_management_started_at", None),
        "finished_at": getattr(client, "local_management_finished_at", None),
        "error": getattr(client, "local_management_error", None),
    }
    if include_secret:
        payload["secret"] = getattr(client, "local_management_secret", None)
    return payload


def _local_management_busy(client: Client) -> bool:
    status = str(getattr(client, "local_management_status", "") or "").strip().lower()
    return bool(getattr(client, "local_management_action", None)) and status in LOCAL_MANAGEMENT_BUSY_STATUSES


def _queue_local_management_request(
    client: Client,
    *,
    action: str,
    message: str,
    desired_hostname: Optional[str] = None,
    secret: Optional[str] = None,
) -> None:
    if action not in LOCAL_MANAGEMENT_ACTIONS:
        raise HTTPException(status_code=400, detail="Ugyldig lokal klienthandling")
    if _local_management_busy(client):
        raise HTTPException(status_code=409, detail="Der er allerede en lokal klienthandling i gang på klienten")
    client.local_management_action = action
    client.local_management_request_id = secrets.token_urlsafe(18)
    client.local_management_desired_hostname = desired_hostname
    client.local_management_secret = secret
    client.local_management_status = "pending"
    client.local_management_message = message
    client.local_management_requested_at = utcnow()
    client.local_management_started_at = None
    client.local_management_finished_at = None
    client.local_management_error = None


def _normalize_kiosk_url(value):
    if value is None:
        return None
    url = str(value).strip()
    if not url:
        return None
    lower = url.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        raise HTTPException(status_code=400, detail="Kiosk URL skal starte med http:// eller https://")
    if len(url) > 2048:
        raise HTTPException(status_code=400, detail="Kiosk URL er for lang")
    return url


def _validate_display_resolution_update(client: Client, client_update: ClientUpdate, fields: set[str]) -> None:
    desired_changed = bool(DISPLAY_RESOLUTION_DESIRED_FIELDS & set(fields))
    report_changed = bool(DISPLAY_RESOLUTION_CLIENT_REPORT_FIELDS & set(fields))

    if desired_changed:
        mode = str(_field_value(client, client_update, fields, "display_resolution_mode", "auto") or "auto").strip().lower()
        preset = str(_field_value(client, client_update, fields, "display_resolution_preset", "auto") or "auto").strip().lower()
        rotation = str(_field_value(client, client_update, fields, "display_resolution_rotation", "normal") or "normal").strip().lower()
        width = _field_value(client, client_update, fields, "display_resolution_width", None)
        height = _field_value(client, client_update, fields, "display_resolution_height", None)
        refresh = _field_value(client, client_update, fields, "display_resolution_refresh_rate", None)

        if mode not in VALID_DISPLAY_RESOLUTION_MODES:
            raise HTTPException(status_code=400, detail=f"Ugyldig display_resolution_mode '{mode}'")
        if preset not in DISPLAY_RESOLUTION_PRESETS:
            raise HTTPException(status_code=400, detail=f"Ugyldig display_resolution_preset '{preset}'")
        if rotation not in VALID_DISPLAY_ROTATIONS:
            raise HTTPException(status_code=400, detail=f"Ugyldig display_resolution_rotation '{rotation}'")

        if mode == "auto" or preset == "auto":
            return

        if width is None or height is None:
            raise HTTPException(status_code=400, detail="Bredde og højde er påkrævet ved fast skærmopløsning")
        try:
            w = int(width)
            h = int(height)
        except Exception:
            raise HTTPException(status_code=400, detail="Bredde/højde skal være heltal")
        if w < 320 or h < 240 or w > 8192 or h > 8192:
            raise HTTPException(status_code=400, detail="Skærmopløsning skal være mellem 320×240 og 8192×8192")

        if refresh not in (None, ""):
            try:
                r = float(refresh)
            except Exception:
                raise HTTPException(status_code=400, detail="Refresh rate skal være et tal")
            if r < 1 or r > 240:
                raise HTTPException(status_code=400, detail="Refresh rate skal være mellem 1 og 240 Hz")

    if "display_resolution_action" in fields:
        action_value = getattr(client_update, "display_resolution_action", None)
        if action_value not in (None, ""):
            action = str(action_value).strip().lower()
            if action not in VALID_DISPLAY_RESOLUTION_ACTIONS:
                raise HTTPException(status_code=400, detail=f"Ugyldig display_resolution_action '{action}'")

    if report_changed:
        status_value = getattr(client_update, "display_resolution_status", None)
        if "display_resolution_status" in fields and status_value is not None:
            status = str(status_value).strip().lower()
            if status not in VALID_DISPLAY_STATUSES:
                raise HTTPException(status_code=400, detail=f"Ugyldig display_resolution_status '{status}'")


def _apply_display_resolution_fields(client: Client, client_update: ClientUpdate, fields: set[str]) -> None:
    if "display_resolution_preset" in fields:
        client.display_resolution_preset = (client_update.display_resolution_preset or "auto")
    if "display_resolution_mode" in fields:
        client.display_resolution_mode = (client_update.display_resolution_mode or "auto")
    if "display_resolution_width" in fields:
        client.display_resolution_width = client_update.display_resolution_width
    if "display_resolution_height" in fields:
        client.display_resolution_height = client_update.display_resolution_height
    if "display_resolution_refresh_rate" in fields:
        client.display_resolution_refresh_rate = client_update.display_resolution_refresh_rate
    if "display_resolution_rotation" in fields:
        client.display_resolution_rotation = client_update.display_resolution_rotation or "normal"

    if "display_resolution_action" in fields:
        action_value = client_update.display_resolution_action
        client.display_resolution_action = str(action_value).strip().lower() if action_value not in (None, "") else None

    desired_changed = bool(DISPLAY_RESOLUTION_DESIRED_FIELDS & set(fields))
    action_requested = "display_resolution_action" in fields and getattr(client, "display_resolution_action", None) in VALID_DISPLAY_RESOLUTION_ACTIONS

    if desired_changed:
        if "display_resolution_action" not in fields:
            client.display_resolution_action = "apply"
        client.display_resolution_updated_at = utcnow()
        client.display_resolution_status = "pending"
        client.display_resolution_error = None
    elif action_requested:
        client.display_resolution_updated_at = utcnow()
        client.display_resolution_status = "pending"
        client.display_resolution_error = None

    if "display_resolution_current_output" in fields:
        client.display_resolution_current_output = client_update.display_resolution_current_output
    if "display_resolution_current_width" in fields:
        client.display_resolution_current_width = client_update.display_resolution_current_width
    if "display_resolution_current_height" in fields:
        client.display_resolution_current_height = client_update.display_resolution_current_height
    if "display_resolution_current_refresh_rate" in fields:
        client.display_resolution_current_refresh_rate = client_update.display_resolution_current_refresh_rate
    if "display_resolution_status" in fields:
        client.display_resolution_status = client_update.display_resolution_status
    if "display_resolution_error" in fields:
        client.display_resolution_error = client_update.display_resolution_error
    if "display_resolution_last_applied_at" in fields:
        client.display_resolution_last_applied_at = client_update.display_resolution_last_applied_at
    if "display_detected_outputs" in fields:
        client.display_detected_outputs = client_update.display_detected_outputs
    if "display_detected_updated_at" in fields:
        client.display_detected_updated_at = client_update.display_detected_updated_at

def is_online(client: Client) -> bool:
    last_seen = _as_naive_utc(client.last_seen)
    if last_seen is None:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - last_seen) < timedelta(seconds=ONLINE_TIMEOUT_SECONDS)


def _client_is_deleted(client: Client) -> bool:
    return getattr(client, "deleted_at", None) is not None or str(getattr(client, "status", "") or "").lower() == "deleted"


VIEWER_ROLE = "viewer"
OPERATOR_USER_ROLES = {"bruger"}
USER_CHROME_COMMANDS = {"start", "stop", "reset_browser", "sleep", "wakeup"}
ADMIN_CHROME_COMMANDS = USER_CHROME_COMMANDS | {"reboot"}
ADMIN_UPDATE_FIELDS = {
    "locality", "kiosk_url", "browser_refresh_interval_sec",
    "pending_reboot",
    "display_resolution_mode", "display_resolution_width", "display_resolution_height",
    "display_resolution_refresh_rate", "display_resolution_output", "display_resolution_action",
}
USER_UPDATE_FIELDS = {"locality", "kiosk_url"}


def _same_organization(user, client: Client) -> bool:
    user_org = getattr(user, "organization_id", None)
    client_org = getattr(client, "organization_id", None)
    return user_org is not None and client_org is not None and user_org == client_org


def _client_is_approved(client: Client) -> bool:
    return str(getattr(client, "status", "") or "").lower() == "approved"


def _require_admin_client_access(user, client: Client) -> None:
    if getattr(user, "is_superadmin", False):
        return
    if getattr(user, "is_admin", False) and _same_organization(user, client):
        return
    raise HTTPException(status_code=403, detail="Du har ikke adgang til denne klient")


def _require_client_read_access(principal, client: Client, *, include_deleted: bool = False) -> None:
    if principal_is_client(principal):
        require_client_self_or_user(principal, client.id)
        return

    if _client_is_deleted(client) and not include_deleted:
        raise HTTPException(status_code=404, detail="Client not found")

    if getattr(principal, "is_superadmin", False):
        return

    # Se adgang er global demo-/læseadgang: må se, men aldrig ændre.
    if getattr(principal, "role", None) == VIEWER_ROLE:
        return

    if getattr(principal, "is_admin", False):
        if _same_organization(principal, client):
            return
        raise HTTPException(status_code=403, detail="Du har ikke adgang til denne klient")

    if getattr(principal, "role", None) == "bruger":
        if _client_is_approved(client) and _same_organization(principal, client):
            return

    raise HTTPException(status_code=403, detail="Du har ikke adgang til denne klient")


def _require_client_status_write_access(principal, client: Client) -> None:
    if principal_is_client(principal):
        require_client_self_or_user(principal, client.id)
        return
    _require_admin_client_access(principal, client)


def _require_client_operator_access(user, client: Client, action: str) -> None:
    if principal_is_client(user):
        raise HTTPException(status_code=403, detail="Klient-token må ikke sende browserkommandoer")

    action = _normalize_chrome_action_name(action) or ""

    if getattr(user, "is_superadmin", False):
        return

    if getattr(user, "is_admin", False):
        if not _same_organization(user, client):
            raise HTTPException(status_code=403, detail="Du har ikke adgang til denne klient")
        if action in ADMIN_CHROME_COMMANDS:
            return
        raise HTTPException(status_code=403, detail=f"Handlingen '{action}' kræver superadmin")

    if getattr(user, "role", None) in OPERATOR_USER_ROLES:
        if _client_is_approved(client) and _same_organization(user, client) and action in USER_CHROME_COMMANDS:
            return
        raise HTTPException(status_code=403, detail="Du har ikke adgang til denne handling")

    raise HTTPException(status_code=403, detail="Se adgang har kun læseadgang")


def _allowed_user_update_fields(user) -> set[str]:
    if getattr(user, "is_superadmin", False):
        return set(ClientUpdate.model_fields.keys())
    if getattr(user, "is_admin", False):
        return set(ADMIN_UPDATE_FIELDS)
    if getattr(user, "role", None) == "bruger":
        return set(USER_UPDATE_FIELDS)
    return set()


SYSTEM_TERMINAL_STEPS = {
    "system_reboot_countdown",
    "system_rebooting",
    "system_shutting_down",
}

CHROME_RUNNING_STEPS = {
    "start_chrome",
    "chrome_opened_manual",
}

CHROME_STOPPED_STEPS = {
    "chrome_closed_programmatically",
    "chrome_closed_manual",
    "shutdown_chrome",
    "system_sleep",
    "system_sleep_complete",
    "display_sleep",
    "display_sleep_complete",
    "display_wake",
    "display_wake_complete",
    "system_wake",
    "system_wake_complete",
    "system_rebooting",
    "system_shutting_down",
}


def _infer_chrome_running_from_status(status: Optional[str], step: Optional[str]) -> Optional[bool]:
    """Best-effort runtime flag for the control room.

    The backend cannot inspect the actual Chrome process, but it can expose the
    latest client-reported status consistently so the frontend does not have to
    parse Danish status text in several components. Return None when the latest
    step/status is transitional or unknown.
    """
    step_norm = str(step or "").strip().lower()
    if step_norm in CHROME_RUNNING_STEPS:
        return True
    if step_norm in CHROME_STOPPED_STEPS:
        return False

    status_norm = str(status or "").strip().lower()
    if any(token in status_norm for token in ("kiosk browser kører", "browser kører", "browser startet")):
        return True
    if any(token in status_norm for token in ("browser lukket", "browser stoppet", "lukket ved systemstart")):
        return False
    return None


NETWORK_OK_TYPES = {"lan", "ethernet", "wired", "wifi", "wi-fi", "wlan"}
NETWORK_EMPTY_VALUES = {"", "none", "no_network", "ingen", "ukendt", "unknown", "offline", "disconnected", "not_connected"}


def _has_network_value(value: Optional[str]) -> bool:
    raw = str(value or "").strip()
    return bool(raw) and raw.lower() not in NETWORK_EMPTY_VALUES


def _derive_network_status(client: Client, *, online: Optional[bool] = None) -> Dict[str, Any]:
    """Derivér en læsestatus for klientens netværk uden at gætte på processer.

    Backend kan ikke modtage en live-fejl fra klienten, når netværket helt er
    væk. Derfor er den autoritative server-status:
      - offline: heartbeat/chrome-status er for gammel
      - no_network: klienten er online, men den seneste diagnostik siger at der
        ikke findes aktiv IP/type/interface
      - ok: klienten er online og diagnostik har en aktiv forbindelse
      - unknown: klienten er online, men har endnu ikke sendt netværksdiagnostik
    """
    if online is None:
        online = is_online(client)

    active_type = str(getattr(client, "active_network_type", "") or "").strip()
    active_ip = str(getattr(client, "active_network_ip", "") or "").strip()
    active_interface = str(getattr(client, "active_network_interface", "") or "").strip()
    active_mac = str(getattr(client, "active_network_mac", "") or "").strip()
    wifi_ip = str(getattr(client, "wifi_ip_address", "") or "").strip()
    lan_ip = str(getattr(client, "lan_ip_address", "") or "").strip()
    diagnostics_at = getattr(client, "diagnostics_updated_at", None)

    if not online:
        return {
            "network_status": "offline",
            "network_status_message": "Klienten har ingen forbindelse til backend",
            "network_status_color": "red",
            "network_has_connection": False,
        }

    has_active_network = any(_has_network_value(v) for v in (active_type, active_ip, active_interface, active_mac))
    has_adapter_ip = any(_has_network_value(v) for v in (wifi_ip, lan_ip))

    if has_active_network or has_adapter_ip:
        label = active_type or ("WiFi" if _has_network_value(wifi_ip) else "LAN" if _has_network_value(lan_ip) else "netværk")
        ip = active_ip or wifi_ip or lan_ip
        suffix = f" · {ip}" if _has_network_value(ip) else ""
        return {
            "network_status": "ok",
            "network_status_message": f"Netværk aktivt: {label}{suffix}",
            "network_status_color": "green",
            "network_has_connection": True,
        }

    if diagnostics_at is not None:
        return {
            "network_status": "no_network",
            "network_status_message": "Ingen aktiv netværksforbindelse registreret på klienten",
            "network_status_color": "red",
            "network_has_connection": False,
        }

    return {
        "network_status": "unknown",
        "network_status_message": "Netværksstatus ukendt — afventer diagnostik fra klienten",
        "network_status_color": "orange",
        "network_has_connection": None,
    }


def _set_runtime_read_attr(obj, key: str, value) -> None:
    """
    Sæt afledte læsefelter på en SQLModel-instans uden at kræve,
    at feltet findes som DB-kolonne på selve Client-modellen.

    SQLModel/Pydantic v2 afviser normalt setattr(obj, "ukendt_felt", ...).
    ClientRead må gerne have ekstra runtime-felter som network_status, men
    Client-tabellen skal ikke have dem som persistente kolonner.
    """
    try:
        setattr(obj, key, value)
    except ValueError as exc:
        if "has no field" not in str(exc):
            raise
        try:
            obj.__dict__[key] = value
        except Exception:
            object.__setattr__(obj, key, value)


def _apply_network_status_for_read(client: Client, *, online: Optional[bool] = None) -> None:
    for key, value in _derive_network_status(client, online=online).items():
        _set_runtime_read_attr(client, key, value)


def _client_network_unavailable(client: Client, *, online: Optional[bool] = None) -> Optional[str]:
    status = _derive_network_status(client, online=online)
    if status.get("network_has_connection") is False:
        return status.get("network_status_message") or "Klienten har ingen aktiv netværksforbindelse"
    return None

BOOT_RECOVERED_CHROME_STATUS = "Klient online efter genstart — afventer aktuel browserstatus"
BOOT_RECOVERED_CHROME_COLOR = "orange"
# Hvis klienten er online igen og uptime er lav, men DB stadig viser et
# reboot-/shutdown-step, er det næsten altid en stale status fra før boot.
BOOT_RECOVERED_UPTIME_GRACE_SECONDS = int(os.getenv("CLIENTFLOW_BOOT_RECOVERED_UPTIME_GRACE_SECONDS", "900"))

# Terminale OS-update steps, som ikke må holde state=updating/pending_os_update
# fast efter en rigtig reboot. Fejl-steps holdes udenfor, så fejl ikke skjules.
OS_UPDATE_BOOT_TERMINAL_STEPS = {
    "os_update_none",
    "os_update_complete",
    "os_rebooting",
}


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        return _as_naive_utc(dt)
    except Exception:
        return None


def _client_uptime_seconds(client: Client) -> Optional[int]:
    try:
        if client.uptime in (None, ""):
            return None
        return int(float(str(client.uptime)))
    except Exception:
        return None


def _step_time_before_current_boot(client: Client, step_time) -> bool:
    step_time = _as_naive_utc(step_time)
    uptime_seconds = _client_uptime_seconds(client)
    if step_time is None or uptime_seconds is None:
        return False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_boot_time = now - timedelta(seconds=uptime_seconds)
    return step_time < (current_boot_time - timedelta(seconds=2))


def is_step_from_previous_boot(client: Client) -> bool:
    """
    Efter reboot kan DB stadig indeholde chrome_step='system_rebooting'.
    Hvis klienten igen sender uptime, kan vi beregne nuværende boot-tidspunkt.
    Ligger chrome_last_updated før boot-tidspunktet, er step'et fra før reboot
    og bør ikke bruges til banner/lås i frontend.
    """
    step = str(client.chrome_step or "").lower()
    if step not in SYSTEM_TERMINAL_STEPS:
        return False

    if client.uptime in (None, "") or client.chrome_last_updated is None:
        return False

    try:
        uptime_seconds = int(float(str(client.uptime)))
    except Exception:
        return False

    # Undgå at små clock-skævheder rydder et helt nyt step.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_boot_time = now - timedelta(seconds=uptime_seconds)
    step_time = _as_naive_utc(client.chrome_last_updated)

    return step_time is not None and step_time < (current_boot_time - timedelta(seconds=2))


def _looks_like_boot_recovered_stale_step(client: Client, *, online: Optional[bool] = None) -> bool:
    step = str(getattr(client, "chrome_step", "") or "").strip().lower()
    if step not in SYSTEM_TERMINAL_STEPS:
        return False
    if is_step_from_previous_boot(client):
        return True
    if online is None:
        online = is_online(client)
    if not online:
        return False
    # Beskyt aktiv reboot/shutdown: hvis backend stadig har en eksplicit pending-flag,
    # må UI gerne vise at handlingen er i gang.
    if getattr(client, "pending_reboot", False) or getattr(client, "pending_shutdown", False):
        return False
    uptime_seconds = _client_uptime_seconds(client)
    return uptime_seconds is not None and 0 <= uptime_seconds <= BOOT_RECOVERED_UPTIME_GRACE_SECONDS


def _pending_action_name(client: Client) -> str:
    return _normalize_chrome_action_name(
        getattr(getattr(client, "pending_chrome_action", None), "value", None)
        or getattr(client, "pending_chrome_action", None)
    ) or "none"


def _normalize_runtime_state(client: Client, *, online: Optional[bool] = None) -> bool:
    """Normalisér stale runtime-state på tværs af read/heartbeat/update.

    `state` bør primært være klientens varige runtime-tilstand. Transiente
    handlinger som reboot/shutdown styres af pending_* og chrome_step. Efter en
    rigtig boot må gamle terminale steps derfor ikke holde Controlroom låst.
    Returnerer True hvis objektet blev ændret og bør committes af caller.
    """
    changed = False
    if online is None:
        online = is_online(client)

    state = str(getattr(client, "state", "") or "").strip().lower()
    step = str(getattr(client, "chrome_step", "") or "").strip().lower()
    pending_action = _pending_action_name(client)
    pending_reboot = bool(getattr(client, "pending_reboot", False))
    pending_shutdown = bool(getattr(client, "pending_shutdown", False))
    active_terminal_step = step in SYSTEM_TERMINAL_STEPS and not is_step_from_previous_boot(client)

    if _looks_like_boot_recovered_stale_step(client, online=online):
        if getattr(client, "chrome_status", None) != BOOT_RECOVERED_CHROME_STATUS:
            client.chrome_status = BOOT_RECOVERED_CHROME_STATUS
            changed = True
        if getattr(client, "chrome_color", None) != BOOT_RECOVERED_CHROME_COLOR:
            client.chrome_color = BOOT_RECOVERED_CHROME_COLOR
            changed = True
        if getattr(client, "chrome_step", None) is not None:
            client.chrome_step = None
            changed = True
        if state in {"rebooting", "shutdown"}:
            client.state = "normal"
            state = "normal"
            changed = True

    # Frontend bruger state=rebooting/shutdown til at låse UI. Den lås må kun
    # være aktiv, mens der faktisk er pending flag eller et aktuelt terminal-step.
    if (
        online
        and state in {"rebooting", "shutdown"}
        and not pending_reboot
        and not pending_shutdown
        and not active_terminal_step
    ):
        client.state = "normal"
        state = "normal"
        changed = True

    # Efter OS-update reboot kan DB stå med pending_os_update/state=updating, selv
    # om klienten igen er online. Ryd kun terminale success/none steps fra før
    # nuværende boot; error bevares.
    if online and bool(getattr(client, "pending_os_update", False)):
        step_before_boot = _step_time_before_current_boot(client, getattr(client, "chrome_last_updated", None))
        if (
            pending_action in {"", "none", "os_update"}
            and step in OS_UPDATE_BOOT_TERMINAL_STEPS
            and (step_before_boot or step in {"os_update_none", "os_update_complete"})
        ):
            client.pending_os_update = False
            changed = True
            if pending_action == "os_update":
                client.pending_chrome_action = ChromeAction.NONE
                client.pending_chrome_action_source = None
            if str(getattr(client, "state", "") or "").strip().lower() == "updating":
                client.state = "normal"
            client.chrome_status = "Ubuntu-opdatering afsluttet — klient online"
            client.chrome_color = "green"

    # ClientFlow-update: hvis update-substate er terminal og der ikke er aktive
    # pending actions, må generisk state ikke blive hængende på updating.
    client_update_status = str(getattr(client, "client_update_status", "") or "").strip().lower()
    if (
        online
        and str(getattr(client, "state", "") or "").strip().lower() == "updating"
        and pending_action in {"", "none"}
        and not bool(getattr(client, "pending_os_update", False))
        and (not client_update_status or client_update_status in CLIENTFLOW_UPDATE_TERMINAL_STATUSES)
    ):
        client.state = "normal"
        changed = True

    return changed


def _apply_runtime_status_for_read(client: Client, *, online: Optional[bool] = None) -> None:
    """Sanitér læse-respons uden commit, så Controlroom ikke viser stale state."""
    if online is None:
        online = is_online(client)
    _normalize_runtime_state(client, online=online)
    _apply_network_status_for_read(client, online=online)



@router.get("/clients/me", response_model=List[ClientRead])
def get_clients_for_my_organization(session=Depends(get_session), user=Depends(get_current_user)):
    if not user.organization_id:
        return []
    clients = session.exec(
        select(Client).where(Client.status == "approved", Client.organization_id == user.organization_id, Client.deleted_at == None)
    ).all()
    for client in clients:
        client.isOnline = is_online(client)
        _apply_runtime_status_for_read(client, online=client.isOnline)
    clients.sort(key=lambda c: (c.sort_order is None, c.sort_order if c.sort_order is not None else 9999, c.id))
    return clients


@router.get("/clients/", response_model=List[ClientRead])
def get_clients(session=Depends(get_session), user=Depends(get_current_user)):
    query = select(Client).where(Client.deleted_at == None)

    if getattr(user, "is_superadmin", False):
        pass
    elif getattr(user, "role", None) == VIEWER_ROLE:
        # Se adgang kan navigere rundt og se alle klienter som demo/læseadgang.
        pass
    elif getattr(user, "is_admin", False):
        query = query.where(Client.organization_id == user.organization_id)
    else:
        query = query.where(
            Client.status == "approved",
            Client.organization_id == user.organization_id,
        )

    clients = session.exec(query).all()
    for client in clients:
        client.isOnline = is_online(client)
        _apply_runtime_status_for_read(client, online=client.isOnline)
    clients.sort(key=lambda c: (c.sort_order is None, c.sort_order if c.sort_order is not None else 9999, c.id))
    return clients


@router.get("/clients/deleted", response_model=List[ClientRead])
def get_deleted_clients(session=Depends(get_session), user=Depends(get_current_user)):
    if not getattr(user, "is_superadmin", False) and getattr(user, "role", None) != VIEWER_ROLE:
        raise HTTPException(status_code=403, detail="Papirkurv kræver superadministrator eller Se adgang")
    query = select(Client).where(Client.deleted_at != None)
    clients = session.exec(query).all()
    for client in clients:
        client.isOnline = is_online(client)
        _apply_runtime_status_for_read(client, online=client.isOnline)
    clients.sort(key=lambda c: (c.deleted_at is None, c.deleted_at or datetime.min), reverse=True)
    return clients


@router.get("/clients/deleted/", response_model=List[ClientRead])
def get_deleted_clients_slash(session=Depends(get_session), user=Depends(get_current_user)):
    return get_deleted_clients(session=session, user=user)


@router.get("/clients/{id}/", response_model=ClientRead)
def get_client(id: int, include_deleted: bool = False, session=Depends(get_session), user=Depends(get_current_user_or_client)):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.isOnline = is_online(client)
    _require_client_read_access(user, client, include_deleted=include_deleted)
    _apply_runtime_status_for_read(client, online=client.isOnline)
    return client


@router.get("/clients/{id}/local-management")
def get_client_local_management(
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_user_or_client),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_client_read_access(user, client)
    include_secret = False
    if principal_is_client(user):
        require_client_self_or_user(user, id)
        include_secret = True
    return _local_management_payload(client, include_secret=include_secret)


@router.post("/clients/{id}/local-management/cfadmin-password")
def request_cfadmin_password_change(
    id: int,
    data: LocalCfadminPasswordRequest,
    session=Depends(get_session),
    user=Depends(get_current_admin_user),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not getattr(user, "is_superadmin", False):
        raise HTTPException(status_code=403, detail="Kun superadmin kan ændre cfadmin-adgangskode")
    _require_admin_client_access(user, client)

    password = _validate_local_password(data.password)
    _queue_local_management_request(
        client,
        action="cfadmin_password",
        secret=password,
        message="Afventer klient: cfadmin-adgangskode ændres lokalt",
    )
    session.add(client)
    session.commit()
    session.refresh(client)
    return _local_management_payload(client, include_secret=False)


@router.post("/clients/{id}/local-management/hostname")
def request_local_hostname_change(
    id: int,
    data: LocalHostnameRequest,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    display_name = _normalize_local_client_display_name(data.name)
    hostname = _derive_linux_hostname_from_client_name(display_name)
    client.name = display_name
    _queue_local_management_request(
        client,
        action="hostname",
        desired_hostname=hostname,
        message=f"Afventer klient: lokalt klientnavn ændres til {display_name} (hostname: {hostname})",
    )
    # _queue_local_management_request nulstiller ikke client.name, men vi sætter igen
    # efter kaldet, så _local_management_payload kan medtage display-navnet.
    client.name = display_name
    session.add(client)
    session.commit()
    session.refresh(client)
    return _local_management_payload(client, include_secret=False) | {"name": client.name}


@router.put("/clients/{id}/local-management/status")
def update_client_local_management_status(
    id: int,
    data: LocalManagementStatusRequest,
    session=Depends(get_session),
    user=Depends(get_current_user_or_client),
):
    if not principal_is_client(user):
        raise HTTPException(status_code=403, detail="Kun klient-token må opdatere lokal klientstyringsstatus")
    require_client_self_or_user(user, id)
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    request_id = str(data.request_id or "").strip()
    if not request_id or request_id != str(getattr(client, "local_management_request_id", "") or ""):
        raise HTTPException(status_code=409, detail="Lokal klientstyrings-request matcher ikke aktiv request")

    status = str(data.status or "").strip().lower()
    if status not in VALID_LOCAL_MANAGEMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Ugyldig lokal klientstyringsstatus '{data.status}'")

    client.local_management_status = status
    client.local_management_message = (data.message or "")[:500] or client.local_management_message
    client.local_management_error = (data.error or "")[:800] or None
    if status == "running":
        client.local_management_started_at = client.local_management_started_at or utcnow()
    if status in {"success", "error", "ready"}:
        client.local_management_finished_at = utcnow()
        # One-time secrets må ikke blive liggende i databasen, når klienten har kvitteret.
        client.local_management_secret = None
        client.local_management_action = None
        client.local_management_desired_hostname = None
    client.last_seen = utcnow()
    session.add(client)
    session.commit()
    session.refresh(client)
    return _local_management_payload(client, include_secret=False)


@router.get("/clients/{id}/chrome-status")
def get_chrome_status(id: int, session=Depends(get_session), user=Depends(get_current_user_or_client)):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_client_read_access(user, client)

    online = is_online(client)
    _normalize_runtime_state(client, online=online)
    stale_boot_status = _looks_like_boot_recovered_stale_step(client, online=online)

    # FIX: Læser chrome_step fra database, men filtrerer gamle system-steps fra
    # forrige boot. Ellers kan frontend blive ved med at vise
    # "Klient genstarter..." efter klienten er kommet online igen.
    step_obj = None
    chrome_step_value = None if stale_boot_status else client.chrome_step
    chrome_status_value = BOOT_RECOVERED_CHROME_STATUS if stale_boot_status else (client.chrome_status or "unknown")
    chrome_color_value = BOOT_RECOVERED_CHROME_COLOR if stale_boot_status else client.chrome_color
    state_value = client.state

    if chrome_step_value:
        step_obj = {
            "step": chrome_step_value,
            "timestamp": (
                _as_naive_utc(client.chrome_last_updated).isoformat() + "Z"
                if client.chrome_last_updated else None
            ),
        }

    pending_action = _chrome_action_value(client.pending_chrome_action) or "none"

    return {
        "client_id": client.id,
        "chrome_status": chrome_status_value,
        "chrome_last_updated": client.chrome_last_updated,
        "chrome_color": chrome_color_value,
        "chrome_step": chrome_step_value,
        "chrome_running": _infer_chrome_running_from_status(chrome_status_value, chrome_step_value),
        **_derive_network_status(client, online=online),
        "step": step_obj,
        "last_seen": client.last_seen,
        "uptime": client.uptime,

        # Vigtigt for ClientDetailsPage: den poller dette endpoint hvert sekund.
        # Uden isOnline her bliver siden ved med at bruge den gamle client.isOnline
        # fra initial getClient/silentRefresh.
        "isOnline": online,
        "is_online": online,

        # Gør frontend i stand til at slippe låse/banner uden at vente på fuldt
        # /clients/{id}/ refresh.
        "state": state_value,
        "pending_chrome_action": pending_action,
        "pending_chrome_action_source": None if pending_action in (None, "none") else getattr(client, "pending_chrome_action_source", None),
        "pending_reboot": client.pending_reboot,
        "pending_shutdown": client.pending_shutdown,
        "pending_os_update": getattr(client, "pending_os_update", False),
        "client_version": client.client_version,
        "client_version_patch": getattr(client, "client_version_patch", None),
        "client_version_updated_at": getattr(client, "client_version_updated_at", None),
        "ubuntu_update_status": getattr(client, "ubuntu_update_status", None),
        "ubuntu_update_step": getattr(client, "ubuntu_update_step", None),
        "ubuntu_update_message": getattr(client, "ubuntu_update_message", None),
        "ubuntu_update_error": getattr(client, "ubuntu_update_error", None),
        "ubuntu_update_started_at": getattr(client, "ubuntu_update_started_at", None),
        "ubuntu_update_updated_at": getattr(client, "ubuntu_update_updated_at", None),
        "ubuntu_update_finished_at": getattr(client, "ubuntu_update_finished_at", None),
        "ubuntu_update_progress": getattr(client, "ubuntu_update_progress", None),
        "ubuntu_update_package_count": getattr(client, "ubuntu_update_package_count", None),
        "ubuntu_update_reboot_required": getattr(client, "ubuntu_update_reboot_required", None),
        "ubuntu_version": getattr(client, "ubuntu_version", None),
        "service_selfupdate_status": getattr(client, "service_selfupdate_status", None),
        "service_ubuntu_update_status": getattr(client, "service_ubuntu_update_status", None),
        "ubuntu_updates_available": getattr(client, "ubuntu_updates_available", 0) or 0,
        "client_update_status": client.client_update_status or "ready",
        "client_update_message": client.client_update_message,
        "client_update_requested_at": client.client_update_requested_at,
        "client_update_started_at": client.client_update_started_at,
        "client_update_finished_at": client.client_update_finished_at,
        "client_update_error": client.client_update_error,
        "browser_refresh_interval_sec": _normalize_browser_refresh_interval(getattr(client, "browser_refresh_interval_sec", None)),
        "diagnostics_updated_at": client.diagnostics_updated_at,
        "system_timezone": client.system_timezone,
        "ntp_enabled": client.ntp_enabled,
        "ntp_synchronized": client.ntp_synchronized,
        "client_time_utc": client.client_time_utc,
        "clock_drift_seconds": client.clock_drift_seconds,
        "time_sync_status": client.time_sync_status,
        "time_sync_message": client.time_sync_message,
        "active_network_type": client.active_network_type,
        "active_network_interface": client.active_network_interface,
        "active_network_ip": client.active_network_ip,
        "active_network_mac": client.active_network_mac,
        "wifi_ip_address": client.wifi_ip_address,
        "wifi_mac_address": client.wifi_mac_address,
        "lan_ip_address": client.lan_ip_address,
        "lan_mac_address": client.lan_mac_address,
        "display_resolution_preset": client.display_resolution_preset or "auto",
        "display_resolution_mode": client.display_resolution_mode or "auto",
        "display_resolution_width": client.display_resolution_width,
        "display_resolution_height": client.display_resolution_height,
        "display_resolution_refresh_rate": client.display_resolution_refresh_rate,
        "display_resolution_rotation": client.display_resolution_rotation or "normal",
        "display_resolution_updated_at": client.display_resolution_updated_at,
        "display_resolution_current_output": client.display_resolution_current_output,
        "display_resolution_current_width": client.display_resolution_current_width,
        "display_resolution_current_height": client.display_resolution_current_height,
        "display_resolution_current_refresh_rate": client.display_resolution_current_refresh_rate,
        "display_resolution_status": client.display_resolution_status or "unknown",
        "display_resolution_error": client.display_resolution_error,
        "display_resolution_last_applied_at": client.display_resolution_last_applied_at,
        "display_detected_outputs": client.display_detected_outputs or [],
        "display_detected_updated_at": client.display_detected_updated_at,
        # v7.1.34: ClientDetailsPage poller /chrome-status hvert sekund.
        # Send livestream runtime med her, så Start kiosk ikke bliver låst af
        # stale client.livestream_status fra initial /clients/{id}/-snapshot.
        "livestream_status": getattr(client, "livestream_status", None),
        "livestream_process_status": getattr(client, "livestream_process_status", None),
        "livestream_desired_state": getattr(client, "livestream_desired_state", None),
        "livestream_stop_reason": getattr(client, "livestream_stop_reason", None),
        "desktop_lockdown_enabled": getattr(client, "desktop_lockdown_enabled", False),
        "desktop_lockdown_status": getattr(client, "desktop_lockdown_status", None) or "unknown",
        "desktop_lockdown_message": getattr(client, "desktop_lockdown_message", None),
        "desktop_lockdown_updated_at": getattr(client, "desktop_lockdown_updated_at", None),
        "desktop_lockdown_last_applied_at": getattr(client, "desktop_lockdown_last_applied_at", None),
    }

@router.put("/clients/{id}/chrome-status")
def update_chrome_status(
    id: int,
    data: dict = Body(...),
    session=Depends(get_session),
    user=Depends(get_current_user_or_client),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_client_status_write_access(user, client)
    step_name = str(data.get("chrome_step") or "").strip().lower()
    step_time = _parse_iso_datetime(data.get("chrome_step_timestamp"))
    stale_step_from_previous_boot = (
        step_name in SYSTEM_TERMINAL_STEPS
        and step_time is not None
        and _step_time_before_current_boot(client, step_time)
    )

    if stale_step_from_previous_boot:
        # Gamle klienter kunne gensende system_rebooting efter boot. Det må ikke
        # overskrive den aktuelle Controlroom-status.
        if str(getattr(client, "state", "") or "").strip().lower() in {"rebooting", "shutdown"}:
            client.state = "normal"
    else:
        if data.get("chrome_status") is not None:
            client.chrome_status = data.get("chrome_status")
        if data.get("chrome_color") is not None:
            client.chrome_color = data.get("chrome_color")
        # FIX: gem chrome_step fra klient så /chrome-status GET kan returnere det
        if data.get("chrome_step") is not None:
            client.chrome_step = data.get("chrome_step")
        client.chrome_last_updated = step_time or utcnow()

    # Et chrome-status push er også et livstegn fra klienten.
    # Best practice: hvis klienten sender versionsfelter her, må de ikke gå tabt.
    # Det gør /chrome-status til et robust live-feed efter self-update/Ubuntu-update,
    # også før næste normale heartbeat eller fulde /update-payload.
    if data.get("client_version") is not None:
        client.client_version = str(data.get("client_version") or "").strip() or client.client_version
    if data.get("ubuntu_version") is not None:
        client.ubuntu_version = str(data.get("ubuntu_version") or "").strip() or client.ubuntu_version

    client.last_seen = utcnow()
    _normalize_runtime_state(client, online=True)
    session.add(client)
    session.commit()
    session.refresh(client)
    return {"ok": True}


@router.put("/clients/{id}/state")
def update_client_state(id: int, data: dict = Body(...), session=Depends(get_session), user=Depends(get_current_user_or_client)):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_client_status_write_access(user, client)
    state = data.get("state")
    if not state:
        raise HTTPException(status_code=400, detail="Missing state")
    state = normalize_client_state(state)
    if state not in VALID_CLIENT_STATES:
        raise HTTPException(status_code=400, detail=f"Ugyldig state '{state}'. Tilladte: {sorted(VALID_CLIENT_STATES)}")
    client.state = state
    session.add(client)
    session.commit()
    session.refresh(client)
    return {"ok": True, "state": client.state}


@router.get("/clients/{id}/state")
def get_client_state(id: int, session=Depends(get_session), user=Depends(get_current_user_or_client)):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_client_read_access(user, client)
    _normalize_runtime_state(client)
    return {"state": client.state}


def _normalize_livestream_source(source) -> Optional[str]:
    if source is None:
        return None
    if not isinstance(source, str):
        raise HTTPException(status_code=400, detail="Ugyldig source-værdi")
    normalized = source.strip().lower()
    if normalized not in VALID_PENDING_CHROME_ACTION_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Ugyldig source '{source}'. Tilladte: {sorted(VALID_PENDING_CHROME_ACTION_SOURCES)}",
        )
    return normalized


@router.post("/clients/{id}/chrome-command")
def set_chrome_command(
    id: int,
    data: dict = Body(...),
    session=Depends(get_session),
    user=Depends(get_current_user_or_client),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    action = _normalize_chrome_action_name(data.get("action"))
    source = data.get("source")

    _require_client_operator_access(user, client, action)

    normalized_source = None
    if source is not None:
        if not isinstance(source, str):
            raise HTTPException(status_code=400, detail="Ugyldig source-værdi")
        src_lower = source.strip().lower()
        if src_lower not in VALID_PENDING_CHROME_ACTION_SOURCES:
            raise HTTPException(
                status_code=400,
                detail=f"Ugyldig source '{source}'. Tilladte: {sorted(VALID_PENDING_CHROME_ACTION_SOURCES)}",
            )
        normalized_source = src_lower

    current_pca = _normalize_chrome_action_name(
        getattr(client.pending_chrome_action, "value", None) or str(client.pending_chrome_action or "none")
    ) or "none"

    network_error = _client_network_unavailable(client)
    if network_error:
        raise HTTPException(status_code=409, detail=network_error)

    state_guard_result = _validate_chrome_command_state(client, action, current_pca)
    if state_guard_result is not None:
        principal_type, principal_id, principal_role = _principal_log_context(user)
        logger.info(
            "client_action_guard client_id=%s action=%s current=%s state=%s principal_type=%s principal_id=%s role=%s",
            id,
            action,
            current_pca,
            _client_state_value(client),
            principal_type,
            principal_id,
            principal_role,
        )
        return state_guard_result

    if (
        action in BLOCKING_ACTIONS
        and current_pca in BLOCKING_ACTIONS
        and current_pca != action
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Handling '{current_pca}' er allerede igang — "
                f"vent til klienten har fuldført den, før du sender '{action}'"
            ),
        )

    if action in BLOCKING_ACTIONS and current_pca == action:
        raise HTTPException(
            status_code=409,
            detail=f"Handling '{action}' er allerede igang på klienten",
        )

    try:
        chrome_action = ChromeAction(action)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Ugyldig action '{action}'")

    old_pca = _chrome_action_value(client.pending_chrome_action) or "none"
    old_source = getattr(client, "pending_chrome_action_source", None)

    client.pending_chrome_action = chrome_action

    if chrome_action == ChromeAction.NONE:
        client.pending_chrome_action_source = None
    elif normalized_source is None:
        # Undgå at en gammel source="actionbutton" hænger ved, hvis en anden
        # kilde sætter en ny action uden source.
        client.pending_chrome_action_source = None
    else:
        client.pending_chrome_action_source = normalized_source

    principal_type, principal_id, principal_role = _principal_log_context(user)
    logger.info(
        "client_action_updated client_id=%s old_action=%s old_source=%s new_action=%s new_source=%s principal_type=%s principal_id=%s role=%s",
        id,
        old_pca,
        old_source,
        client.pending_chrome_action.value if client.pending_chrome_action else None,
        getattr(client, "pending_chrome_action_source", None),
        principal_type,
        principal_id,
        principal_role,
    )
    session.add(client)
    session.commit()
    session.refresh(client)
    return {
        "ok": True,
        "pending_chrome_action": client.pending_chrome_action.value,
        "pending_chrome_action_source": getattr(client, "pending_chrome_action_source", None),
    }


@router.get("/clients/{id}/chrome-command")
def get_chrome_command(id: int, session=Depends(get_session), user=Depends(get_current_user_or_client)):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_client_read_access(user, client)
    action = client.pending_chrome_action.value if client.pending_chrome_action else None
    source = None if action in (None, "none") else getattr(client, "pending_chrome_action_source", None)
    return {
        "action": action,
        "source": source,
    }


def _os_update_is_stale(client: Client) -> bool:
    """Returnér True hvis en Ubuntu/OS update ser ud til at være efterladt i busy-state."""
    if not getattr(client, "pending_os_update", False) and getattr(client, "state", None) != "updating":
        return False

    pca = _normalize_chrome_action_name(
        getattr(getattr(client, "pending_chrome_action", None), "value", None)
        or getattr(client, "pending_chrome_action", None)
    ) or "none"

    # Kun OS-update-flowet skal stale-resettes her. ClientFlow selfupdate har egen logik.
    if pca not in ("", "none", "os_update"):
        return False

    ref = _as_naive_utc(getattr(client, "chrome_last_updated", None)) or _as_naive_utc(getattr(client, "last_seen", None))
    if ref is None:
        return False

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - ref).total_seconds() > OS_UPDATE_STALE_SECONDS


def _normalize_os_update_state_if_finished(client: Client) -> None:
    """Ryd state=updating hvis OS-update allerede er ryddet fra pending felter."""
    pca = _normalize_chrome_action_name(
        getattr(getattr(client, "pending_chrome_action", None), "value", None)
        or getattr(client, "pending_chrome_action", None)
    ) or "none"
    if getattr(client, "state", None) == "updating" and pca in ("", "none") and not getattr(client, "pending_os_update", False):
        client.state = "normal"


@router.post("/clients/{id}/os-update")
async def trigger_os_update(
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_admin_client_access(user, client)
    if not is_online(client):
        raise HTTPException(status_code=400, detail="Klienten er offline — kan ikke starte opdatering")

    _normalize_os_update_state_if_finished(client)

    if client.state == "updating" or getattr(client, "pending_os_update", False):
        if _os_update_is_stale(client):
            client.pending_chrome_action = ChromeAction.NONE
            client.pending_chrome_action_source = None
            client.pending_os_update = False
            client.state = "error"
            client.chrome_status = "Tidligere Ubuntu-opdatering blev nulstillet som forældet/stalled"
            client.chrome_color = "red"
            client.chrome_step = "os_update_failed"
            client.chrome_last_updated = utcnow()
            session.add(client)
            session.commit()
            session.refresh(client)
        else:
            raise HTTPException(status_code=409, detail=_current_update_detail(client))

    now = utcnow()
    client.pending_chrome_action = ChromeAction.OS_UPDATE
    client.pending_chrome_action_source = "actionbutton"
    client.pending_os_update = True
    client.state = "updating"
    # Bruges som request-tidsstempel/nøgle for klientens idempotens-marker.
    client.chrome_status = "Ubuntu-opdatering bestilt fra backend"
    client.chrome_color = "orange"
    client.chrome_step = "os_update_requested"
    client.chrome_last_updated = now
    client.ubuntu_update_status = "requested"
    client.ubuntu_update_step = "os_update_requested"
    client.ubuntu_update_message = "Ubuntu-opdatering bestilt fra backend"
    client.ubuntu_update_error = None
    client.ubuntu_update_started_at = None
    client.ubuntu_update_updated_at = now
    client.ubuntu_update_finished_at = None
    client.ubuntu_update_progress = 0
    client.ubuntu_update_package_count = client.ubuntu_updates_available
    client.ubuntu_update_reboot_required = False
    session.add(client)
    session.commit()
    session.refresh(client)
    return {
        "ok": True,
        "message": f"OS-opdatering bestilt for klient {id}",
        "pending_chrome_action": client.pending_chrome_action.value,
        "pending_os_update": client.pending_os_update,
        "state": client.state,
        "chrome_step": client.chrome_step,
        "chrome_last_updated": client.chrome_last_updated,
    }


@router.post("/clients/{id}/os-update/reset")
async def reset_os_update(
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """Nulstil en fastlåst Ubuntu/OS update uden at starte en ny update."""
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_admin_client_access(user, client)

    now = utcnow()
    client.pending_chrome_action = ChromeAction.NONE
    client.pending_chrome_action_source = None
    client.pending_os_update = False
    client.state = "normal"
    client.chrome_status = "Ubuntu-opdateringsstatus nulstillet af admin"
    client.chrome_color = "green"
    client.chrome_step = "os_update_reset"
    client.chrome_last_updated = now
    client.ubuntu_update_status = "ready"
    client.ubuntu_update_step = "os_update_reset"
    client.ubuntu_update_message = "Ubuntu-opdateringsstatus nulstillet af admin"
    client.ubuntu_update_error = None
    client.ubuntu_update_updated_at = now
    client.ubuntu_update_finished_at = now
    client.ubuntu_update_progress = 0
    client.ubuntu_update_reboot_required = False

    session.add(client)
    session.commit()
    session.refresh(client)

    return {
        "ok": True,
        "message": f"Ubuntu-opdateringsstatus nulstillet for klient {id}",
        "pending_chrome_action": client.pending_chrome_action.value,
        "pending_os_update": client.pending_os_update,
        "state": client.state,
        "chrome_status": client.chrome_status,
        "chrome_step": client.chrome_step,
        "chrome_last_updated": client.chrome_last_updated,
    }



def _clientflow_update_is_stale(client: Client) -> bool:
    """Returnér True hvis en ClientFlow update ser ud til at være efterladt i busy-state."""
    status = str(getattr(client, "client_update_status", "") or "").strip().lower()
    if status not in CLIENTFLOW_UPDATE_BUSY_STATUSES:
        return False

    ref = (
        _as_naive_utc(getattr(client, "client_update_started_at", None))
        or _as_naive_utc(getattr(client, "client_update_requested_at", None))
    )
    if ref is None:
        return False

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - ref).total_seconds() > CLIENTFLOW_STALE_UPDATE_SECONDS


def _normalize_clientflow_update_state_if_finished(client: Client) -> None:
    """Ryd state=updating hvis update-felterne allerede er i en terminal tilstand."""
    status = str(getattr(client, "client_update_status", "") or "").strip().lower()
    pca = _normalize_chrome_action_name(
        getattr(getattr(client, "pending_chrome_action", None), "value", None)
        or getattr(client, "pending_chrome_action", None)
    ) or "none"

    if (
        getattr(client, "state", None) == "updating"
        and pca in ("", "none")
        and not getattr(client, "pending_os_update", False)
        and status in CLIENTFLOW_UPDATE_TERMINAL_STATUSES
    ):
        client.state = "normal"

@router.post("/clients/{id}/clientflow-update")
async def trigger_clientflow_update(
    id: int,
    http_request: Request,
    update_request: ClientFlowUpdateRequest = Body(default_factory=ClientFlowUpdateRequest),
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """Bestil en katalogstyret ClientFlow update eller eksplicit rollback."""
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_admin_client_access(user, client)
    if not is_online(client):
        raise HTTPException(status_code=400, detail="Klienten er offline — kan ikke starte ClientFlow-opdatering")

    try:
        catalog = load_catalog()
        release = resolve_release(update_request.target_version)
        validate_release_compatibility(
            release,
            current_version=client.client_version,
            ubuntu_version=client.ubuntu_version,
        )
    except ClientFlowCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target_version = str(release["version"])
    current_version = str(client.client_version or "").strip().lstrip("vV")
    latest_version = str(catalog["latest_stable"])
    is_downgrade = bool(current_version and compare_versions(target_version, current_version) < 0)
    is_non_latest_without_current = bool(not current_version and target_version != latest_version)
    requires_downgrade_confirmation = is_downgrade or is_non_latest_without_current

    if requires_downgrade_confirmation:
        if release.get("rollback_allowed") is not True:
            raise HTTPException(status_code=400, detail=f"ClientFlow {target_version} er ikke godkendt som rollback-version")
        if not update_request.confirm_downgrade:
            raise HTTPException(status_code=400, detail="Nedgradering kræver eksplicit bekræftelse")
        if not str(update_request.reason or "").strip():
            raise HTTPException(status_code=400, detail="Nedgradering kræver en begrundelse")

    _normalize_clientflow_update_state_if_finished(client)

    if client.state == "updating":
        if _clientflow_update_is_stale(client):
            client.pending_chrome_action = ChromeAction.NONE
            client.pending_chrome_action_source = None
            client.pending_os_update = False
            client.state = "error"
            client.client_update_status = "error"
            client.client_update_message = "Tidligere ClientFlow-opdatering blev nulstillet som forældet/stalled"
            client.client_update_error = "Update var stadig i busy-state efter timeout"
            client.client_update_finished_at = utcnow()
            session.add(client)
            session.commit()
            session.refresh(client)
        else:
            raise HTTPException(status_code=409, detail=_current_update_detail(client))

    now = utcnow()
    deployment_sequence = max(
        int(client.client_update_deployment_sequence or 0),
        int(client.client_update_applied_deployment_sequence or 0),
    ) + 1
    reason = str(update_request.reason or "").strip() or None
    client.pending_chrome_action = ChromeAction.CLIENTFLOW_UPDATE
    client.pending_chrome_action_source = "actionbutton"
    client.state = "updating"
    client.client_update_status = "requested"
    client.client_update_target_version = target_version
    client.client_update_target_release_sequence = int(release["release_sequence"])
    client.client_update_deployment_sequence = deployment_sequence
    client.client_update_allow_downgrade = requires_downgrade_confirmation
    client.client_update_reason = reason
    client.client_update_message = (
        f"Rollback til ClientFlow {target_version} bestilt fra backend"
        if requires_downgrade_confirmation
        else f"ClientFlow {target_version} bestilt fra backend"
    )
    client.client_update_requested_at = now
    client.client_update_started_at = None
    client.client_update_finished_at = None
    client.client_update_error = None
    add_audit_log(
        session,
        action="clientflow_downgrade_requested" if requires_downgrade_confirmation else "clientflow_update_requested",
        request=http_request,
        actor=user,
        target_organization_id=client.organization_id,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        severity="critical" if requires_downgrade_confirmation else "warning",
        is_critical=requires_downgrade_confirmation,
        details={
            "current_version": current_version or None,
            "target_version": target_version,
            "latest_stable": latest_version,
            "target_release_sequence": release["release_sequence"],
            "deployment_sequence": deployment_sequence,
            "reason": reason,
        },
    )
    session.add(client)
    session.commit()
    session.refresh(client)
    return {
        "ok": True,
        "message": client.client_update_message,
        "pending_chrome_action": client.pending_chrome_action.value,
        "state": client.state,
        "client_update_status": client.client_update_status,
        "client_update_message": client.client_update_message,
        "client_update_requested_at": client.client_update_requested_at,
        "client_update_target_version": client.client_update_target_version,
        "client_update_target_release_sequence": client.client_update_target_release_sequence,
        "client_update_deployment_sequence": client.client_update_deployment_sequence,
        "client_update_allow_downgrade": client.client_update_allow_downgrade,
    }


@router.post("/clients/{id}/clientflow-update/reset")
async def reset_clientflow_update(
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """Nulstil en fastlåst ClientFlow self-update uden at starte en ny update."""
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_admin_client_access(user, client)

    now = utcnow()
    client.pending_chrome_action = ChromeAction.NONE
    client.pending_chrome_action_source = None
    client.state = "normal"
    client.client_update_status = "ready"
    client.client_update_message = "ClientFlow-opdateringsstatus nulstillet af admin"
    client.client_update_error = None
    client.client_update_target_version = "latest"
    client.client_update_target_release_sequence = None
    client.client_update_allow_downgrade = False
    client.client_update_reason = None
    client.client_update_finished_at = now

    session.add(client)
    session.commit()
    session.refresh(client)

    return {
        "ok": True,
        "message": f"ClientFlow-opdateringsstatus nulstillet for klient {id}",
        "pending_chrome_action": client.pending_chrome_action.value,
        "state": client.state,
        "client_update_status": client.client_update_status,
        "client_update_message": client.client_update_message,
        "client_update_finished_at": client.client_update_finished_at,
    }


@router.get("/clients/{id}/ubuntu-updates")
def get_ubuntu_updates(id: int, session=Depends(get_session), user=Depends(get_current_user_or_client)):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _require_client_read_access(user, client)
    return {
        "client_id": client.id,
        "ubuntu_updates_available": client.ubuntu_updates_available or 0,
        "pending_os_update": client.pending_os_update or False,
        "ubuntu_version": client.ubuntu_version,
    }


@router.post("/clients/", response_model=ClientRead)
async def create_client(
    request: Request,
    client_in: ClientCreate,
    session=Depends(get_session),
    user=Depends(get_current_admin_user),
):
    resolved_organization_id = client_in.organization_id
    if not getattr(user, "is_superadmin", False):
        resolved_organization_id = getattr(user, "organization_id", None)
    if resolved_organization_id is not None and not session.get(Organization, resolved_organization_id):
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")

    client = Client(
        name=client_in.name,
        locality=client_in.locality,
        wifi_ip_address=client_in.wifi_ip_address,
        wifi_mac_address=client_in.wifi_mac_address,
        lan_ip_address=client_in.lan_ip_address,
        lan_mac_address=client_in.lan_mac_address,
        status="pending",
        deleted_at=None,
        deleted_by_user_id=None,
        deleted_reason=None,
        deleted_previous_status=None,
        restored_at=None,
        restored_by_user_id=None,
        isOnline=False,
        last_seen=None,
        sort_order=client_in.sort_order,
        kiosk_url=getattr(client_in, "kiosk_url", None),
        browser_refresh_interval_sec=_normalize_browser_refresh_interval(getattr(client_in, "browser_refresh_interval_sec", None)),
        ubuntu_version=getattr(client_in, "ubuntu_version", None),
        uptime=getattr(client_in, "uptime", None),
        chrome_status=getattr(client_in, "chrome_status", "unknown"),
        chrome_last_updated=None,
        chrome_color=getattr(client_in, "chrome_color", None),
        chrome_step=getattr(client_in, "chrome_step", None),
        pending_reboot=False,
        pending_shutdown=False,
        pending_chrome_action=getattr(client_in, "pending_chrome_action", ChromeAction.NONE),
        pending_chrome_action_source=getattr(client_in, "pending_chrome_action_source", None),
        organization_id=resolved_organization_id,
        state=getattr(client_in, "state", "normal"),
        livestream_status="idle",
        livestream_last_segment=None,
        livestream_last_error=None,
        diagnostics_updated_at=getattr(client_in, "diagnostics_updated_at", None),
        system_timezone=getattr(client_in, "system_timezone", None),
        ntp_enabled=getattr(client_in, "ntp_enabled", None),
        ntp_synchronized=getattr(client_in, "ntp_synchronized", None),
        client_time_utc=getattr(client_in, "client_time_utc", None),
        clock_drift_seconds=None,
        time_sync_status="unknown",
        time_sync_message=None,
        active_network_type=getattr(client_in, "active_network_type", None),
        active_network_interface=getattr(client_in, "active_network_interface", None),
        active_network_ip=getattr(client_in, "active_network_ip", None),
        active_network_mac=getattr(client_in, "active_network_mac", None),
        service_clientflow_status=getattr(client_in, "service_clientflow_status", None),
        service_calendar_status=getattr(client_in, "service_calendar_status", None),
        service_browser_guard_status=getattr(client_in, "service_browser_guard_status", None),
        service_remote_terminal_status=getattr(client_in, "service_remote_terminal_status", None),
        service_admin_terminal_status=getattr(client_in, "service_admin_terminal_status", None),
        service_remote_desktop_status=getattr(client_in, "service_remote_desktop_status", None),
        service_kiosk_x11_guard_status=getattr(client_in, "service_kiosk_x11_guard_status", None),
        service_livestream_status=getattr(client_in, "service_livestream_status", None),
        service_selfupdate_status=getattr(client_in, "service_selfupdate_status", None),
        service_ubuntu_update_status=getattr(client_in, "service_ubuntu_update_status", None),
        service_local_reboot_reporter_status=getattr(client_in, "service_local_reboot_reporter_status", None),
        service_local_shutdown_reporter_status=getattr(client_in, "service_local_shutdown_reporter_status", None),
        livestream_process_status=getattr(client_in, "livestream_process_status", None),
        ubuntu_updates_available=getattr(client_in, "ubuntu_updates_available", 0),
        pending_os_update=getattr(client_in, "pending_os_update", False),
        desktop_lockdown_enabled=getattr(client_in, "desktop_lockdown_enabled", False),
        desktop_lockdown_status=getattr(client_in, "desktop_lockdown_status", "unknown"),
        desktop_lockdown_message=getattr(client_in, "desktop_lockdown_message", None),
        desktop_lockdown_updated_at=getattr(client_in, "desktop_lockdown_updated_at", None),
        desktop_lockdown_last_applied_at=getattr(client_in, "desktop_lockdown_last_applied_at", None),
        client_version=getattr(client_in, "client_version", None),
        client_update_status=getattr(client_in, "client_update_status", "ready"),
        client_update_message=getattr(client_in, "client_update_message", None),
        client_update_requested_at=getattr(client_in, "client_update_requested_at", None),
        client_update_started_at=getattr(client_in, "client_update_started_at", None),
        client_update_finished_at=getattr(client_in, "client_update_finished_at", None),
        client_update_error=getattr(client_in, "client_update_error", None),
        display_resolution_preset=getattr(client_in, "display_resolution_preset", "auto"),
        display_resolution_mode=getattr(client_in, "display_resolution_mode", "auto"),
        display_resolution_width=getattr(client_in, "display_resolution_width", None),
        display_resolution_height=getattr(client_in, "display_resolution_height", None),
        display_resolution_refresh_rate=getattr(client_in, "display_resolution_refresh_rate", None),
        display_resolution_rotation=getattr(client_in, "display_resolution_rotation", "normal"),
        display_resolution_action=getattr(client_in, "display_resolution_action", None),
        display_resolution_updated_at=getattr(client_in, "display_resolution_updated_at", None),
        display_resolution_current_output=getattr(client_in, "display_resolution_current_output", None),
        display_resolution_current_width=getattr(client_in, "display_resolution_current_width", None),
        display_resolution_current_height=getattr(client_in, "display_resolution_current_height", None),
        display_resolution_current_refresh_rate=getattr(client_in, "display_resolution_current_refresh_rate", None),
        display_resolution_status=getattr(client_in, "display_resolution_status", "unknown"),
        display_resolution_error=getattr(client_in, "display_resolution_error", None),
        display_resolution_last_applied_at=getattr(client_in, "display_resolution_last_applied_at", None),
        display_detected_outputs=getattr(client_in, "display_detected_outputs", None),
        display_detected_updated_at=getattr(client_in, "display_detected_updated_at", None),
    )
    _apply_time_integrity_report(
        client,
        {field for field in ("system_timezone", "ntp_enabled", "ntp_synchronized", "client_time_utc")
         if getattr(client_in, field, None) is not None},
    )
    session.add(client)
    session.flush()
    add_audit_log(
        session,
        action="client_created",
        request=request,
        actor=user,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        target_organization_id=client.organization_id,
        details={"status": client.status, "organization_id": client.organization_id},
    )
    session.commit()
    session.refresh(client)
    return client


def _authorize_client_update_fields(user, client: Client, client_update: ClientUpdate, fields: set[str]) -> None:
    """Validate exactly which patch fields the authenticated principal may send."""
    if principal_is_client(user):
        allowed_fields = set(CLIENT_SELF_UPDATE_FIELDS)
        action_value = getattr(client_update, "display_resolution_action", None)
        if "display_resolution_action" in fields and action_value in (None, ""):
            allowed_fields.add("display_resolution_action")
        forbidden = sorted(fields - allowed_fields)
        if forbidden:
            raise HTTPException(status_code=403, detail=f"Klient-token må ikke opdatere disse felter: {forbidden}")
        return

    _require_client_read_access(user, client)
    allowed_fields = _allowed_user_update_fields(user)
    forbidden = sorted(fields - allowed_fields)
    if forbidden:
        if getattr(user, "role", None) == "viewer":
            raise HTTPException(status_code=403, detail="Se adgang har kun læseadgang")
        raise HTTPException(status_code=403, detail=f"Du må ikke opdatere disse felter: {forbidden}")
    if "organization_id" in fields and not getattr(user, "is_superadmin", False):
        raise HTTPException(status_code=403, detail="Brug change-organization endpointet til organisationsskift")


def _validate_client_update_privileges(user, client: Client, fields: set[str]) -> None:
    if (DISPLAY_RESOLUTION_DESIRED_FIELDS | DISPLAY_RESOLUTION_ACTION_FIELDS) & fields:
        if principal_is_client(user):
            raise HTTPException(status_code=403, detail="Klient-token må ikke ændre ønsket skærmopløsning")
        if not getattr(user, "is_superadmin", False):
            if not (getattr(user, "role", None) == "admin" and _same_organization(user, client)):
                raise HTTPException(status_code=403, detail="Skærmopløsning kan kun ændres af superadministrator eller administrator for egen organisation")

    if DESKTOP_LOCKDOWN_DESIRED_FIELDS & fields:
        if principal_is_client(user):
            raise HTTPException(status_code=403, detail="Klient-token må ikke ændre ønsket kiosk lockdown")
        if not getattr(user, "is_superadmin", False):
            raise HTTPException(status_code=403, detail="Kiosk lockdown må kun ændres af superadmin")


def _validate_client_update_command_availability(user, client: Client, client_update: ClientUpdate, fields: set[str]) -> None:
    if principal_is_client(user):
        return
    wants_reboot = "pending_reboot" in fields and bool(client_update.pending_reboot)
    wants_shutdown = "pending_shutdown" in fields and bool(client_update.pending_shutdown)
    display_action_value = str(getattr(client_update, "display_resolution_action", "") or "").strip().lower()
    wants_display_action = "display_resolution_action" in fields and display_action_value in VALID_DISPLAY_RESOLUTION_ACTIONS
    if wants_reboot or wants_shutdown or wants_display_action:
        network_error = _client_network_unavailable(client)
        if network_error:
            raise HTTPException(status_code=409, detail=network_error)


@router.put("/clients/{id}/update", response_model=ClientRead)
async def update_client(
    id: int,
    client_update: ClientUpdate,
    session=Depends(get_session),
    user=Depends(get_current_user_or_client),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    fields = set(client_update.model_fields_set)
    _authorize_client_update_fields(user, client, client_update, fields)
    _validate_client_update_privileges(user, client, fields)
    _validate_client_update_command_availability(user, client, client_update, fields)

    _validate_display_resolution_update(client, client_update, fields)
    if "name" in fields: client.name = _normalize_client_name(client_update.name)
    if "machine_id" in fields: client.machine_id = client_update.machine_id
    if "locality" in fields: client.locality = client_update.locality
    if "sort_order" in fields: client.sort_order = client_update.sort_order
    if "kiosk_url" in fields: client.kiosk_url = _normalize_kiosk_url(client_update.kiosk_url)
    if "browser_refresh_interval_sec" in fields:
        client.browser_refresh_interval_sec = _normalize_browser_refresh_interval(client_update.browser_refresh_interval_sec)
    if "ubuntu_version" in fields: client.ubuntu_version = client_update.ubuntu_version
    if "uptime" in fields: client.uptime = client_update.uptime
    if "wifi_ip_address" in fields: client.wifi_ip_address = client_update.wifi_ip_address
    if "wifi_mac_address" in fields: client.wifi_mac_address = client_update.wifi_mac_address
    if "lan_ip_address" in fields: client.lan_ip_address = client_update.lan_ip_address
    if "lan_mac_address" in fields: client.lan_mac_address = client_update.lan_mac_address
    if "chrome_status" in fields: client.chrome_status = client_update.chrome_status
    if "chrome_color" in fields: client.chrome_color = client_update.chrome_color
    # FIX: gem chrome_step i DB så /chrome-status GET kan returnere det korrekt
    if "chrome_step" in fields: client.chrome_step = client_update.chrome_step
    if "chrome_last_updated" in fields:
        client.chrome_last_updated = client_update.chrome_last_updated
    elif "chrome_status" in fields or "chrome_step" in fields:
        client.chrome_last_updated = utcnow()
    if "last_seen" in fields: client.last_seen = client_update.last_seen
    if "created_at" in fields: client.created_at = client_update.created_at
    if "pending_reboot" in fields:
        client.pending_reboot = client_update.pending_reboot
        if client.pending_reboot and "state" not in fields:
            client.state = "rebooting"
        if client.pending_reboot:
            now_event = _now_naive_utc()
            client.last_power_event = "reboot_requested"
            client.last_power_event_at = now_event
            client.last_power_event_source = _principal_power_source(user)
            client.last_reboot_started_at = now_event
    if "pending_shutdown" in fields:
        client.pending_shutdown = client_update.pending_shutdown
        if client.pending_shutdown and "state" not in fields:
            client.state = "shutdown"
        if client.pending_shutdown:
            now_event = _now_naive_utc()
            client.last_power_event = "shutdown_requested"
            client.last_power_event_at = now_event
            client.last_power_event_source = _principal_power_source(user)
            client.last_shutdown_started_at = now_event
    old_pending_action = _chrome_action_value(getattr(client, "pending_chrome_action", None)) or "none"
    old_pending_source = getattr(client, "pending_chrome_action_source", None)

    if "pending_chrome_action" in fields:
        val = client_update.pending_chrome_action
        normalized_val = _normalize_chrome_action_name(val)
        client.pending_chrome_action = ChromeAction.NONE if normalized_val is None else ChromeAction(normalized_val)

        if client.pending_chrome_action == ChromeAction.NONE:
            # Når action ryddes, skal source også ryddes. Ellers kan næste action
            # uden source fejlagtigt ligne "actionbutton" i klientloggen.
            client.pending_chrome_action_source = None
        elif "pending_chrome_action_source" not in fields:
            # Ny action uden source må ikke arve gammel source.
            client.pending_chrome_action_source = None

    if "pending_chrome_action_source" in fields:
        src = client_update.pending_chrome_action_source
        if src is None:
            client.pending_chrome_action_source = None
        else:
            src_lower = str(src).strip().lower()
            if src_lower not in VALID_PENDING_CHROME_ACTION_SOURCES:
                raise HTTPException(status_code=400, detail=f"Ugyldig source '{src}'")
            client.pending_chrome_action_source = src_lower

    if "organization_id" in fields: client.organization_id = client_update.organization_id
    if "state" in fields:
        state = client_update.state
        if state is None:
            client.state = None
        else:
            state_lower = normalize_client_state(state)
            if state_lower not in VALID_CLIENT_STATES:
                raise HTTPException(status_code=400, detail=f"Ugyldig state '{state}'")
            client.state = state_lower

    if POWER_LIFECYCLE_FIELDS & set(fields):
        for lifecycle_field in POWER_LIFECYCLE_FIELDS:
            if lifecycle_field in fields:
                value = getattr(client_update, lifecycle_field)
                if lifecycle_field == "last_power_event":
                    value = _normalize_power_event_value(value)
                elif lifecycle_field == "last_power_event_source" and value is not None:
                    value = str(value).strip().lower()[:80] or None
                elif lifecycle_field == "last_boot_id" and value is not None:
                    value = str(value).strip()[:128] or None
                setattr(client, lifecycle_field, value)

    if "livestream_status" in fields: client.livestream_status = client_update.livestream_status
    if "livestream_last_segment" in fields: client.livestream_last_segment = client_update.livestream_last_segment
    if "livestream_last_error" in fields: client.livestream_last_error = client_update.livestream_last_error
    for diagnostic_field in DIAGNOSTIC_FIELDS:
        if diagnostic_field in fields:
            setattr(client, diagnostic_field, getattr(client_update, diagnostic_field))
    _apply_time_integrity_report(client, set(fields))
    if (DISPLAY_RESOLUTION_DESIRED_FIELDS | DISPLAY_RESOLUTION_ACTION_FIELDS | DISPLAY_RESOLUTION_CLIENT_REPORT_FIELDS) & set(fields):
        _apply_display_resolution_fields(client, client_update, fields)
    if "ubuntu_updates_available" in fields:
        value = client_update.ubuntu_updates_available
        client.ubuntu_updates_available = max(0, int(value or 0))
    if "pending_os_update" in fields:
        client.pending_os_update = client_update.pending_os_update
    if UBUNTU_UPDATE_FIELDS & set(fields):
        if "ubuntu_update_status" in fields:
            value = str(client_update.ubuntu_update_status or "ready").strip().lower()
            if value not in UBUNTU_UPDATE_STATUSES:
                raise HTTPException(status_code=400, detail=f"Ugyldig ubuntu_update_status '{value}'")
            client.ubuntu_update_status = value
        if "ubuntu_update_step" in fields:
            client.ubuntu_update_step = str(client_update.ubuntu_update_step or "").strip()[:120] or None
        if "ubuntu_update_message" in fields:
            client.ubuntu_update_message = str(client_update.ubuntu_update_message or "").strip()[:2000] or None
        if "ubuntu_update_error" in fields:
            client.ubuntu_update_error = str(client_update.ubuntu_update_error or "").strip()[:4000] or None
        for timestamp_field in (
            "ubuntu_update_started_at", "ubuntu_update_updated_at", "ubuntu_update_finished_at"
        ):
            if timestamp_field in fields:
                setattr(client, timestamp_field, getattr(client_update, timestamp_field))
        if "ubuntu_update_progress" in fields:
            progress = client_update.ubuntu_update_progress
            client.ubuntu_update_progress = None if progress is None else max(0, min(100, int(progress)))
        if "ubuntu_update_package_count" in fields:
            count = client_update.ubuntu_update_package_count
            client.ubuntu_update_package_count = None if count is None else max(0, int(count))
        if "ubuntu_update_reboot_required" in fields:
            client.ubuntu_update_reboot_required = client_update.ubuntu_update_reboot_required
    if "desktop_lockdown_enabled" in fields:
        desired_lockdown = bool(client_update.desktop_lockdown_enabled)
        client.desktop_lockdown_enabled = desired_lockdown
        client.desktop_lockdown_updated_at = utcnow()
        client.desktop_lockdown_status = "pending"
        client.desktop_lockdown_message = (
            "Afventer klient: kiosk lockdown anvendes på kiosk-brugeren"
            if desired_lockdown
            else "Afventer klient: kiosk lockdown rulles tilbage på kiosk-brugeren"
        )
    if "desktop_lockdown_status" in fields:
        status_value = (client_update.desktop_lockdown_status or "unknown").strip().lower()
        if status_value not in VALID_DESKTOP_LOCKDOWN_STATUSES:
            status_value = "unknown"
        client.desktop_lockdown_status = status_value
    if "desktop_lockdown_message" in fields:
        client.desktop_lockdown_message = client_update.desktop_lockdown_message
    if "desktop_lockdown_last_applied_at" in fields:
        client.desktop_lockdown_last_applied_at = client_update.desktop_lockdown_last_applied_at
    if "client_version" in fields: client.client_version = client_update.client_version
    if "client_version_patch" in fields: client.client_version_patch = client_update.client_version_patch
    if "client_version_updated_at" in fields: client.client_version_updated_at = client_update.client_version_updated_at
    if "client_update_status" in fields: client.client_update_status = client_update.client_update_status
    if "client_update_message" in fields: client.client_update_message = client_update.client_update_message
    if "client_update_requested_at" in fields: client.client_update_requested_at = client_update.client_update_requested_at
    if "client_update_started_at" in fields: client.client_update_started_at = client_update.client_update_started_at
    if "client_update_finished_at" in fields: client.client_update_finished_at = client_update.client_update_finished_at
    if "client_update_error" in fields: client.client_update_error = client_update.client_update_error
    if "client_update_target_version" in fields: client.client_update_target_version = client_update.client_update_target_version
    if "client_update_target_release_sequence" in fields: client.client_update_target_release_sequence = client_update.client_update_target_release_sequence
    if "client_update_deployment_sequence" in fields: client.client_update_deployment_sequence = max(0, int(client_update.client_update_deployment_sequence or 0))
    if "client_update_applied_deployment_sequence" in fields: client.client_update_applied_deployment_sequence = max(0, int(client_update.client_update_applied_deployment_sequence or 0))
    if "client_update_allow_downgrade" in fields: client.client_update_allow_downgrade = bool(client_update.client_update_allow_downgrade)
    if "client_update_reason" in fields: client.client_update_reason = str(client_update.client_update_reason or "").strip()[:500] or None
    if "display_detected_outputs" in fields: client.display_detected_outputs = client_update.display_detected_outputs
    if "display_detected_updated_at" in fields: client.display_detected_updated_at = client_update.display_detected_updated_at

    if principal_is_client(user):
        _normalize_runtime_state(client, online=True)

    if "pending_chrome_action" in fields or "pending_chrome_action_source" in fields:
        principal_type, principal_id, principal_role = _principal_log_context(user)
        logger.info(
            "client_action_patch client_id=%s old_action=%s old_source=%s new_action=%s new_source=%s principal_type=%s principal_id=%s role=%s",
            id,
            old_pending_action,
            old_pending_source,
            _chrome_action_value(getattr(client, "pending_chrome_action", None)),
            getattr(client, "pending_chrome_action_source", None),
            principal_type,
            principal_id,
            principal_role,
        )
    session.add(client)
    session.commit()
    session.refresh(client)
    return client


@router.put("/clients/{id}/kiosk_url", response_model=ClientRead)
async def update_kiosk_url(
    id: int,
    data: dict = Body(...),
    session=Depends(get_session),
    user=Depends(get_current_user),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if getattr(user, "is_superadmin", False):
        pass
    elif getattr(user, "role", None) in {"admin", "bruger"}:
        if not (_client_is_approved(client) and _same_organization(user, client)):
            raise HTTPException(status_code=403, detail="Du kan kun ændre kiosk URL for egen organisations godkendte klienter")
    else:
        raise HTTPException(status_code=403, detail="Kiosk URL kan ændres af superadministrator, administrator eller bruger for egen organisation")

    if "kiosk_url" not in data:
        raise HTTPException(status_code=400, detail="Missing kiosk_url")

    client.kiosk_url = _normalize_kiosk_url(data.get("kiosk_url"))
    session.add(client)
    session.commit()
    session.refresh(client)
    return client


def _current_season_str() -> str:
    return current_season()


def _validate_calendar_season(season: str) -> str:
    try:
        return validate_supported_season(season)
    except SeasonValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _organization_times_for_season(
    session,
    organization_id: Optional[int],
    season: str,
) -> Dict[str, Dict[str, str]]:
    return effective_organization_times(session, organization_id, season)


def _apply_organization_standard_times_to_existing_markings(
    markings: Dict[str, Any],
    *,
    old_times: Dict[str, Dict[str, str]],
    new_times: Dict[str, Dict[str, str]],
    preserve_manual_times: bool = True,
) -> tuple[Dict[str, Any], int, int]:
    try:
        return apply_standard_times_to_existing_markings(
            markings,
            old_times=old_times,
            new_times=new_times,
            preserve_manual_times=preserve_manual_times,
        )
    except SeasonValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _default_calendar_for_organization_year(
    season: str,
    times: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    try:
        return build_season_calendar(season, times)
    except SeasonValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/clients/{id}/change-organization", response_model=ClientOrganizationChangeResponse)
async def change_client_organization(
    request: Request,
    id: int,
    data: ClientOrganizationChangeRequest,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """
    Skift klientens organisation.

    Valgfrit:
    - apply_organization_standard_times=True opdaterer KUN standardtider på eksisterende tændte kalenderdage.
    - Dagens on/off-status bevares.
    - Slukkede dage bevares.
    - Manuelle tider bevares som standard, hvis de ikke matcher den gamle organisations standardtider.
    """
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if "organization_id" not in data.model_fields_set:
        raise HTTPException(status_code=400, detail="organization_id mangler")

    old_organization_id = client.organization_id
    new_organization_id = data.organization_id

    if new_organization_id is not None and not session.get(Organization, new_organization_id):
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")

    if not getattr(user, "is_superadmin", False):
        # Almindelige admins må kun flytte klienter inden for egen organisation.
        if old_organization_id != user.organization_id or new_organization_id != user.organization_id:
            raise HTTPException(status_code=403, detail="Du må kun ændre klienter i din egen organisation")

    season = _validate_calendar_season(data.season or _current_season_str())
    apply_organization_standard_times = data.apply_organization_standard_times
    preserve_manual_times = data.preserve_manual_times

    result = {
        "calendar_updated": False,
        "calendar_changed_days": 0,
        "manual_days_preserved": 0,
        "season": season,
    }

    if apply_organization_standard_times and new_organization_id is None:
        raise HTTPException(status_code=400, detail="Kan ikke anvende organisationstider uden en organisation")

    client.organization_id = new_organization_id
    session.add(client)

    if apply_organization_standard_times:
        old_times = _organization_times_for_season(session, old_organization_id, season)
        new_times = _organization_times_for_season(session, new_organization_id, season)

        existing = session.exec(
            select(CalendarMarking).where(
                CalendarMarking.season == season,
                CalendarMarking.client_id == client.id,
            )
        ).first()

        if existing:
            updated_markings, changed_count, preserved_manual_count = _apply_organization_standard_times_to_existing_markings(
                existing.markings or {},
                old_times=old_times,
                new_times=new_times,
                preserve_manual_times=preserve_manual_times,
            )
            existing.markings = updated_markings
            session.add(existing)
            result["calendar_changed_days"] = changed_count
            result["manual_days_preserved"] = preserved_manual_count
        else:
            updated_markings = _default_calendar_for_organization_year(season, new_times)
            existing = CalendarMarking(
                season=season,
                client_id=client.id,
                markings=updated_markings,
            )
            session.add(existing)
            result["calendar_changed_days"] = 0
            result["manual_days_preserved"] = 0

        result["calendar_updated"] = True

    add_audit_log(
        session,
        action="client_organization_changed",
        request=request,
        actor=user,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        target_organization_id=new_organization_id,
        details={
            "organization_id_before": old_organization_id,
            "organization_id_after": new_organization_id,
            **result,
        },
    )
    session.commit()
    session.refresh(client)
    client.isOnline = is_online(client)

    return {
        **client.model_dump(),
        "organization_id": client.organization_id,
        **result,
    }


@router.post("/clients/{id}/approve", response_model=ClientRead)
async def approve_client(
    request: Request,
    id: int,
    data: Optional[ClientApprovalRequest] = Body(default=None),
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if _client_is_deleted(client):
        raise HTTPException(status_code=400, detail="Klienten ligger i papirkurven og skal gendannes før godkendelse")

    status_before = client.status
    organization_before = client.organization_id
    if data is not None and "organization_id" in data.model_fields_set:
        if data.organization_id is not None and not session.get(Organization, data.organization_id):
            raise HTTPException(status_code=404, detail="Organisation ikke fundet")
        client.organization_id = data.organization_id

    terminal_identity = session.get(TerminalClient, id)
    remote_desktop_identity = session.get(RemoteDesktopClient, id)
    terminal_credential = session.exec(
        select(TerminalCredential).where(
            TerminalCredential.client_id == id,
            TerminalCredential.revoked_at == None,
        )
    ).first()
    remote_desktop_credential = session.exec(
        select(RemoteDesktopCredential).where(
            RemoteDesktopCredential.client_id == id,
            RemoteDesktopCredential.revoked_at == None,
        )
    ).first()
    if (
        terminal_identity is None
        or remote_desktop_identity is None
        or terminal_credential is None
        or remote_desktop_credential is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Klientens isolerede Terminal/Remote Desktop provisioning er ufuldstændig",
        )

    client.status = "approved"
    terminal_identity.status = "approved"
    terminal_identity.display_name = client.name
    remote_desktop_identity.status = "approved"
    remote_desktop_identity.display_name = client.name
    session.add(terminal_identity)
    session.add(remote_desktop_identity)
    max_sort_order = session.exec(
        select(Client.sort_order)
        .where(Client.status == "approved", Client.sort_order != None)
        .order_by(Client.sort_order.desc())
    ).first()
    client.sort_order = (max_sort_order or 0) + 1
    session.add(client)

    calendar_results = []
    for season_str in current_and_next_seasons():
        organization_times = _organization_times_for_season(
            session,
            client.organization_id,
            season_str,
        )
        _calendar, created, filled_days = ensure_client_calendar(
            session,
            client,
            season_str,
            organization_times,
        )
        calendar_results.append({
            "season": season_str,
            "created": created,
            "filled_days": filled_days,
        })

    add_audit_log(
        session,
        action="client_approved",
        request=request,
        actor=user,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        target_organization_id=client.organization_id,
        details={
            "status_before": status_before,
            "status_after": client.status,
            "organization_id_before": organization_before,
            "organization_id_after": client.organization_id,
            "calendar_seasons": calendar_results,
        },
    )
    session.commit()
    session.refresh(client)
    return client


@router.post("/clients/{id}/heartbeat", response_model=ClientRead)
def client_heartbeat(
    id: int,
    data: dict = Body(default=None),
    session=Depends(get_session),
    user=Depends(get_current_user_or_client),
):
    """
    Heartbeat er klientens hurtige livstegn.

    Vigtigt:
    Webfrontend viser uptime fra backend. Den lokale klient-GUI viser uptime
    direkte fra clientflow_config.json, som opdateres fra /proc/uptime.
    Derfor skal heartbeat også opdatere backend.uptime, ellers kan webvisningen
    være bagud i forhold til den lokale GUI.
    """
    require_client_self_or_user(user, id)
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.last_seen = utcnow()

    if isinstance(data, dict):
        if data.get("uptime") is not None:
            client.uptime = str(data.get("uptime"))
        if data.get("ubuntu_version") is not None:
            client.ubuntu_version = data.get("ubuntu_version")
        if data.get("client_version") is not None:
            client.client_version = data.get("client_version")

        # Valgfrit, men nyttigt hvis heartbeat senere bruges til netværksdata.
        for field in (
            "wifi_ip_address",
            "wifi_mac_address",
            "lan_ip_address",
            "lan_mac_address",
            "diagnostics_updated_at",
            "active_network_type",
            "active_network_interface",
            "active_network_ip",
            "active_network_mac",
            "service_clientflow_status",
            "service_calendar_status",
            "service_browser_guard_status",
            "service_remote_terminal_status",
            "service_admin_terminal_status",
            "service_remote_desktop_status",
            "service_kiosk_x11_guard_status",
            "service_livestream_status",
            "service_selfupdate_status",
            "service_ubuntu_update_status",
            "service_local_reboot_reporter_status",
            "service_local_shutdown_reporter_status",
            "livestream_process_status",
            "system_timezone",
            "ntp_enabled",
            "ntp_synchronized",
            "client_time_utc",
        ):
            if data.get(field) is not None:
                setattr(client, field, data.get(field))
        _apply_time_integrity_report(client, set(data))

    _normalize_runtime_state(client, online=True)
    session.add(client)
    session.commit()
    session.refresh(client)
    client.isOnline = True
    _apply_runtime_status_for_read(client, online=True)
    return client


def _generate_client_secret() -> str:
    """
    Genererer en klienthemmelighed til installerede Ubuntu-klienter.

    Vises kun én gang ved rotate/generering og gemmes kun hashed i databasen.
    """
    return "cf_client_" + secrets.token_urlsafe(32)


def _client_secret_status(client: Client) -> dict:
    return {
        "client_id": client.id,
        "has_client_secret": bool(client.client_secret_hash) and client.client_secret_revoked_at is None,
        "client_secret_created_at": client.client_secret_created_at,
        "client_secret_revoked_at": client.client_secret_revoked_at,
        "enrollment_token_id": client.enrollment_token_id,
        "machine_id": client.machine_id,
        "status": client.status,
        "name": client.name,
    }


@router.get("/clients/{id}/client-secret/status")
def get_client_secret_status(
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """
    Superadmin: se om en eksisterende klient har aktiv client-secret.

    Returnerer aldrig selve secret'en.
    """
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return _client_secret_status(client)


@router.post("/clients/{id}/client-secret/rotate")
def rotate_client_secret(
    request: Request,
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """
    Superadmin: generér/rotér client-secret for en eksisterende klient.

    Bruges til at migrere eksisterende klienter væk fra admin-login.
    Secret'en returneres kun i dette response og kan ikke læses igen bagefter.
    """
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client_secret = _generate_client_secret()
    client.client_secret_hash = get_password_hash(client_secret)
    client.client_secret_created_at = utcnow()
    client.client_secret_revoked_at = None
    client.client_token_version = int(getattr(client, "client_token_version", 0) or 0) + 1

    session.add(client)
    add_audit_log(
        session,
        action="client_secret_rotated",
        request=request,
        actor=user,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        target_organization_id=client.organization_id,
        severity="critical",
        is_critical=True,
        details={"client_token_version": client.client_token_version},
    )
    session.commit()
    session.refresh(client)

    return {
        **_client_secret_status(client),
        "client_secret": client_secret,
    }


@router.post("/clients/{id}/client-secret/revoke")
def revoke_client_secret(
    request: Request,
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """
    Superadmin: tilbagekald client-secret for en eksisterende klient.

    Efter revoke kan klienten ikke længere få /auth/client-token med sin secret.
    """
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.client_secret_revoked_at = utcnow()
    client.client_token_version = int(getattr(client, "client_token_version", 0) or 0) + 1
    session.add(client)
    add_audit_log(
        session,
        action="client_secret_revoked",
        request=request,
        actor=user,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        target_organization_id=client.organization_id,
        severity="critical",
        is_critical=True,
        details={"client_token_version": client.client_token_version},
    )
    session.commit()
    session.refresh(client)

    return _client_secret_status(client)



@router.delete("/clients/{id}/remove")
async def remove_client(
    request: Request,
    id: int,
    data: dict = Body(default=None),
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """Flyt klienten til papirkurv.

    Dette er bevidst en soft delete: klientrækken, client-secret,
    enrollment-link og kalenderdata bevares, så klienten kan gendannes
    uden reinstall eller Neon restore.
    """
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if _client_is_deleted(client):
        return {"ok": True, "removed_client_id": id, "already_deleted": True}

    now = utcnow()
    reason = None
    if isinstance(data, dict):
        raw_reason = data.get("reason") or data.get("deleted_reason")
        reason = str(raw_reason).strip()[:500] if raw_reason else None

    client.deleted_at = now
    client.deleted_by_user_id = getattr(user, "id", None)
    client.deleted_reason = reason
    client.deleted_previous_status = client.status or "approved"
    client.restored_at = None
    client.restored_by_user_id = None
    client.status = "deleted"
    client.isOnline = False
    client.pending_chrome_action = ChromeAction.NONE
    client.pending_chrome_action_source = None

    session.add(client)
    add_audit_log(
        session,
        action="client_soft_deleted",
        request=request,
        actor=user,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        target_organization_id=client.organization_id,
        severity="warning",
        details={"reason": reason, "previous_status": client.deleted_previous_status},
    )
    session.commit()
    session.refresh(client)

    return {
        "ok": True,
        "removed_client_id": id,
        "soft_deleted": True,
        "deleted_at": client.deleted_at,
    }


@router.post("/clients/{id}/restore", response_model=ClientRead)
async def restore_client(
    request: Request,
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """Gendan en klient fra papirkurven."""
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not _client_is_deleted(client):
        client.isOnline = is_online(client)
        return client

    restored_status = client.deleted_previous_status or "approved"
    if restored_status == "deleted":
        restored_status = "approved"

    client.status = restored_status
    client.deleted_at = None
    client.deleted_by_user_id = None
    client.deleted_reason = None
    client.deleted_previous_status = None
    client.restored_at = utcnow()
    client.restored_by_user_id = getattr(user, "id", None)

    session.add(client)
    add_audit_log(
        session,
        action="client_restored",
        request=request,
        actor=user,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        target_organization_id=client.organization_id,
        details={"restored_status": restored_status},
    )
    session.commit()
    session.refresh(client)
    client.isOnline = is_online(client)
    return client


@router.delete("/clients/{id}/purge")
async def purge_client(
    request: Request,
    id: int,
    session=Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    """Slet en klient permanent. Kun for superadmin og kun fra papirkurv.

    Dette er den gamle hard-delete logik: kalenderdata slettes,
    enrollment-token frakobles, og klientrækken fjernes fysisk.
    """
    client = session.get(Client, id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not _client_is_deleted(client):
        raise HTTPException(status_code=400, detail="Klienten skal ligge i papirkurven før permanent sletning")

    try:
        stats = prepare_client_for_permanent_delete(
            session,
            client_id=int(client.id),
            reason="client_permanently_deleted",
        )

        add_audit_log(
            session,
            action="client_permanently_deleted",
            request=request,
            actor=user,
            entity_type="client",
            entity_id=client.id,
            entity_label=client.name,
            target_organization_id=client.organization_id,
            severity="critical",
            is_critical=True,
            details={
                "unlinked_enrollment_tokens": stats.unlinked_enrollment_tokens,
                "terminal_decommissioned": stats.terminal_decommissioned,
                "remote_desktop_decommissioned": stats.remote_desktop_decommissioned,
            },
        )
        session.delete(client)
        session.commit()
        return {
            "ok": True,
            "purged_client_id": id,
            "unlinked_enrollment_tokens": stats.unlinked_enrollment_tokens,
            "terminal_decommissioned": stats.terminal_decommissioned,
            "remote_desktop_decommissioned": stats.remote_desktop_decommissioned,
        }
    except Exception as exc:
        session.rollback()
        log_safe_exception(
            logger,
            exc,
            event="client_permanent_delete_failed",
            level=logging.ERROR,
            client_id=id,
        )
        raise HTTPException(
            status_code=500,
            detail="Kunne ikke slette klient permanent",
        ) from None
