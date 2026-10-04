"""Deterministic Control Room health classification without I/O or DB access."""

from __future__ import annotations

from typing import Any


_BAD_ERROR_STATES = {"error", "failed", "fejl"}
_BAD_SERVICE_STATES = {"failed", "error", "not-found", "missing", "fejl"}


def build_client_health_issues(client: Any) -> list[dict[str, str]]:
    """Return operator-facing issues from already-loaded client/runtime fields.

    Ordinary offline/idle states are deliberately not classified as faults.
    The caller is responsible for role-based rendering of ``required_role``.
    """

    issues: list[dict[str, str]] = []

    def add(
        code: str,
        title: str,
        message: str,
        resolution: str,
        *,
        required_role: str = "admin",
        severity: str = "error",
    ) -> None:
        issues.append(
            {
                "code": code,
                "severity": severity,
                "title": title,
                "message": message,
                "suggested_resolution": resolution,
                "required_role": required_role,
            }
        )

    chrome_color = str(getattr(client, "chrome_color", "") or "").strip().lower()
    if chrome_color == "red":
        add(
            "browser_runtime_error",
            "Browserfejl",
            str(getattr(client, "chrome_status", "") or "Browseren rapporterer en fejl."),
            "Åbn Control Room og kontroller browserstatus. Prøv derefter den relevante browserhandling eller reset, hvis fejlen fortsætter.",
        )

    display_status = str(getattr(client, "display_resolution_status", "") or "").strip().lower()
    display_error = str(getattr(client, "display_resolution_error", "") or "").strip()
    if display_status in _BAD_ERROR_STATES or display_error:
        add(
            "display_resolution_error",
            "Skærmindstilling fejlede",
            display_error or "Klienten rapporterer fejl i skærmopløsningen.",
            "Åbn Control Room og vælg en gyldig skærmopløsning igen. Kontroller skærm/output hvis fejlen gentager sig.",
        )

    livestream_error = str(getattr(client, "livestream_last_error", "") or "").strip()
    if livestream_error:
        add(
            "livestream_error",
            "Livestream-fejl",
            livestream_error,
            "Åbn klientens Livestream og forsøg en kontrolleret genstart. Hvis fejlen fortsætter, skal en superadministrator kontrollere Livestream-services/logs.",
        )

    update_status = str(getattr(client, "ubuntu_update_status", "") or "").strip().lower()
    update_error = str(getattr(client, "ubuntu_update_error", "") or "").strip()
    if update_status in _BAD_ERROR_STATES or update_error:
        add(
            "ubuntu_update_error",
            "Ubuntu-opdatering fejlede",
            update_error or str(getattr(client, "ubuntu_update_message", "") or "Ubuntu-opdateringen rapporterer fejl."),
            "Kontroller opdateringsstatus og systemlog. Denne fejl kræver superadministrator, hvis den ikke kan løses fra den normale Control Room-handling.",
            required_role="superadmin",
        )

    cf_update_status = str(getattr(client, "client_update_status", "") or "").strip().lower()
    cf_update_error = str(getattr(client, "client_update_error", "") or "").strip()
    if cf_update_status in _BAD_ERROR_STATES or cf_update_error:
        add(
            "clientflow_update_error",
            "ClientFlow-opdatering fejlede",
            cf_update_error or str(getattr(client, "client_update_message", "") or "ClientFlow-opdateringen rapporterer fejl."),
            "Kontroller deployment/update-status, release-identitet og updater-log. Kræver superadministrator.",
            required_role="superadmin",
        )

    local_status = str(getattr(client, "local_management_status", "") or "").strip().lower()
    local_error = str(getattr(client, "local_management_error", "") or "").strip()
    if local_status in _BAD_ERROR_STATES or local_error:
        add(
            "local_management_error",
            "Lokal klientstyring fejlede",
            local_error or str(getattr(client, "local_management_message", "") or "Lokal klientstyring rapporterer fejl."),
            "Kontroller den seneste lokale management-handling og system-agenten. Kræver superadministrator ved fortsat fejl.",
            required_role="superadmin",
        )

    lockdown_status = str(getattr(client, "desktop_lockdown_status", "") or "").strip().lower()
    if lockdown_status in {"error", "failed", "rollback", "fejl"}:
        add(
            "kiosk_lockdown_error",
            "Kiosk-lockdown fejlede",
            str(getattr(client, "desktop_lockdown_message", "") or "Kiosk-lockdown er ikke anvendt korrekt."),
            "Kontroller GNOME/DING/Nautilus readiness og lockdown-rollback. Kræver superadministrator.",
            required_role="superadmin",
        )

    time_sync = str(getattr(client, "time_sync_status", "") or "").strip().lower()
    if time_sync == "critical":
        add(
            "time_sync_critical",
            "Kritisk tidsfejl",
            str(getattr(client, "time_sync_message", "") or "Klientens systemtid er ikke korrekt synkroniseret."),
            "Kontroller netværk, tidszone og NTP. Kontakt superadministrator hvis klienten ikke selv genetablerer synkronisering.",
            required_role="superadmin",
        )

    service_fields = (
        ("service_clientflow_status", "Status-agent", "clientflow-status-agent.service"),
        ("service_browser_guard_status", "Browser Guard", "clientflow-browser-guard.service"),
        ("service_remote_desktop_status", "Remote Desktop", "clientflow-remote-desktop-agent.service"),
        ("service_remote_terminal_status", "Terminal", "clientflow-terminal-agent.service"),
    )
    for field, title, unit in service_fields:
        raw = str(getattr(client, field, "") or "").strip()
        if raw.lower() in _BAD_SERVICE_STATES:
            add(
                f"service_{field}_error",
                f"{title}-service fejlede",
                f"{unit}: {raw}",
                f"Kontroller og genstart {unit} efter loggennemgang. Kræver superadministrator.",
                required_role="superadmin",
            )

    return issues[:8]
