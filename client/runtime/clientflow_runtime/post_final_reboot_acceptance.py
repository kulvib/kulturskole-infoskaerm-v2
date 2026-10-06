"""Post-final-reboot customer handoff acceptance gate.

The fresh installer stages a pending customer handoff immediately before its
final reboot. This service runs on the new boot and marks the handoff accepted
only after the complete customer-handoff contract is observable together.

This automated gate is intentionally fail-closed and does not replace the
physical release acceptance test of the exact immutable release bytes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
from urllib.parse import parse_qsl, urlsplit

from .atomic import atomic_write_json
from .config import DomainCredential
from .constants import Domain
from .kiosk_lockdown import apply as apply_lockdown, status as lockdown_status
from .kiosk_session_policy import _active_local_kiosk_session
from .net import DomainTransport

STATE_PATH = Path(os.getenv("CLIENTFLOW_CUSTOMER_HANDOFF_STATE", "/var/lib/clientflow/release/customer-handoff.json"))
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
NAUTILUS = Path("/usr/bin/nautilus")
DISPLAY_CONFIG_PATH = Path("/var/lib/clientflow/display-runtime/configuration.json")
DISPLAY_STATUS_PATH = Path("/var/lib/clientflow/display-runtime/runtime-status.json")
DISPLAY_BOOT_MARKER_PATH = Path("/var/lib/clientflow/display-runtime/browser-boot.json")
PROC_ROOT = Path("/proc")
RUN_USER_ROOT = Path("/run/user")
RUNUSER = Path("/usr/sbin/runuser")
GDBUS = Path("/usr/bin/gdbus")
JOURNALCTL = Path("/usr/bin/journalctl")
SYSTEMCTL = Path("/usr/bin/systemctl")
KIOSK_USER = "clientflow-kiosk"
ADMIN_USER = "cfadmin"
ADMIN_GROUPS = {"sudo", "admin"}
STATE_OWNER_UID = 0
EXPECTED_BOOT_COUNTDOWN_SECONDS = 10

CRITICAL_ACTIVE_UNITS = (
    "clientflow-status-agent.service",
    "clientflow-display-agent.service",
    "clientflow-display-runtime.service",
    "clientflow-browser-guard.service",
    "clientflow-calendar.service",
    "clientflow-livestream-agent.service",
    "clientflow-livestream-broker.service",
    "clientflow-livestream-producer.service",
    "clientflow-livestream-uploader.service",
    "clientflow-remote-desktop-agent.service",
    "clientflow-terminal-agent.service",
    "clientflow-system-agent.service",
    "clientflow-display-power-broker.socket",
    "clientflow-calendar-reboot-broker.socket",
    "clientflow-kiosk-lockdown-broker.socket",
    "clientflow-remote-desktop-capture.socket",
    "clientflow-remote-desktop-input-broker.socket",
    "clientflow-standard-terminal-broker.socket",
    "clientflow-root-terminal-broker.socket",
    "clientflow-system-broker.socket",
    "clientflow-time-integrity.timer",
    "clientflow-kiosk-session-policy.timer",
)

_BROWSER_GUARD_PROBE_JS = r"""
(() => {
  const selectors = [
    '#coiOverlay', '#coiConsentBanner', '#CybotCookiebotDialog',
    '#CybotCookiebotDialogBodyUnderlay', '#CookiebotWidget',
    '#usercentrics-root', '[data-testid="uc-app-container"]',
    '[data-testid="uc-overlay"]', '#onetrust-banner-sdk',
    '#onetrust-consent-sdk', '.didomi-popup-container',
    '.didomi-consent-popup', '.qc-cmp2-container', '.cc-window',
    '.cookie-banner', '.cookie-consent', '.cookie-box', '.cookie-notice',
    '.consent-banner', '.consent-modal', '.CookieConsent',
    '.cookiescript_injected', '[id*="cookie-banner" i]',
    '[id*="cookie-consent" i]', '[class*="cookie-banner" i]',
    '[class*="cookie-consent" i]', '[class*="consent-banner" i]',
    '[class*="consent-modal" i]'
  ];
  const visible = [];
  for (const selector of selectors) {
    for (const el of document.querySelectorAll(selector)) {
      try {
        const style = getComputedStyle(el);
        const box = el.getBoundingClientRect();
        if (style.display !== 'none' && style.visibility !== 'hidden' &&
            Number(style.opacity || '1') !== 0 && box.width > 10 && box.height > 10) {
          visible.push(selector);
        }
      } catch (_) {}
    }
  }
  return {
    href: location.href,
    readyState: document.readyState,
    marker: document.documentElement.getAttribute('data-clientflow-browser-guard'),
    css: !!document.getElementById('clientflow-browser-guard-css'),
    visibleConsent: [...new Set(visible)]
  };
})()
"""


class PostFinalRebootAcceptanceError(RuntimeError):
    pass


def _read_state() -> dict[str, object] | None:
    try:
        meta = STATE_PATH.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_uid != STATE_OWNER_UID or (meta.st_mode & 0o077):
        raise PostFinalRebootAcceptanceError("Customer handoff-state har usikre ownership/permissions")
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PostFinalRebootAcceptanceError("Customer handoff-state er ugyldig") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PostFinalRebootAcceptanceError("Customer handoff-state har ukendt schema")
    return value


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        meta = path.lstat()
        if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_size > 256 * 1024:
            raise PostFinalRebootAcceptanceError(f"{label} er ikke en sikker almindelig fil")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PostFinalRebootAcceptanceError(f"{label} mangler") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PostFinalRebootAcceptanceError(f"{label} er ugyldig") from exc
    if not isinstance(value, dict):
        raise PostFinalRebootAcceptanceError(f"{label} skal være et JSON-objekt")
    return value


def _boot_id() -> str:
    try:
        value = BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise PostFinalRebootAcceptanceError("Kernel boot-id kan ikke læses") from exc
    if not value:
        raise PostFinalRebootAcceptanceError("Kernel boot-id mangler")
    return value


def _group_names(username: str) -> set[str]:
    try:
        record = pwd.getpwnam(username)
    except KeyError as exc:
        raise PostFinalRebootAcceptanceError(f"Canonical konto mangler: {username}") from exc
    import grp
    names: set[str] = set()
    for entry in grp.getgrall():
        if entry.gr_gid == record.pw_gid or username in entry.gr_mem:
            names.add(entry.gr_name)
    return names


def _run(command: list[str], *, timeout: float = 10.0, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PostFinalRebootAcceptanceError(f"Acceptance-check kunne ikke køres: {command[0]}") from exc


def _verify_nautilus_ding_session() -> None:
    if not NAUTILUS.is_file() or not os.access(NAUTILUS, os.X_OK):
        raise PostFinalRebootAcceptanceError("Nautilus mangler eller er ikke eksekverbar efter final reboot")
    try:
        kiosk = pwd.getpwnam(KIOSK_USER)
    except KeyError as exc:
        raise PostFinalRebootAcceptanceError("Canonical kiosk-konto mangler") from exc
    runtime_dir = RUN_USER_ROOT / str(kiosk.pw_uid)
    bus_path = runtime_dir / "bus"
    if not bus_path.exists():
        raise PostFinalRebootAcceptanceError("Kiosk D-Bus-session er endnu ikke klar")
    command = [
        str(RUNUSER), "--user", KIOSK_USER, "--", "/usr/bin/env",
        f"HOME={kiosk.pw_dir}", f"XDG_RUNTIME_DIR={runtime_dir}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={bus_path}",
        str(GDBUS), "call", "--session", "--dest", "org.freedesktop.DBus",
        "--object-path", "/org/freedesktop/DBus", "--method",
        "org.freedesktop.DBus.StartServiceByName", "org.freedesktop.FileManager1", "0",
    ]
    result = _run(command, timeout=8.0)
    if result.returncode != 0 or "uint32" not in result.stdout:
        raise PostFinalRebootAcceptanceError("Nautilus FileManager1 kan ikke aktiveres i kiosk-sessionen")
    journal = _run([
        str(JOURNALCTL), "-b", "--no-pager", "--output=cat",
        "--grep=Nautilus File Manager not found|mandatory to work with Desktop Icons NG",
    ], timeout=8.0)
    if journal.returncode not in {0, 1}:
        raise PostFinalRebootAcceptanceError("Boot-journal kunne ikke verificeres for DING/Nautilus")
    if journal.stdout.strip():
        raise PostFinalRebootAcceptanceError("DING/Nautilus startup-fejl er observeret i det aktuelle boot")


def _verify_display_runtime(current_boot: str) -> str:
    configuration = _read_json_object(DISPLAY_CONFIG_PATH, "Display-konfiguration")
    kiosk_url = str(configuration.get("kiosk_url") or "").strip()
    if not kiosk_url:
        raise PostFinalRebootAcceptanceError("Display-konfiguration mangler kiosk-URL")
    parsed = urlsplit(kiosk_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise PostFinalRebootAcceptanceError("Display-konfigurationens kiosk-URL er ugyldig")

    status = _read_json_object(DISPLAY_STATUS_PATH, "Display runtime-status")
    try:
        browser_pid = int(status.get("browser_pid") or 0)
    except (TypeError, ValueError):
        browser_pid = 0
    if status.get("state") != "running" or status.get("browser_requested") is not True or browser_pid <= 1:
        raise PostFinalRebootAcceptanceError("Browser runtime er ikke verificeret running efter final reboot")
    try:
        cmdline = (PROC_ROOT / str(browser_pid) / "cmdline").read_bytes().split(b"\0")
    except OSError as exc:
        raise PostFinalRebootAcceptanceError("Kørende browser-proces kan ikke verificeres") from exc
    arguments = [item.decode("utf-8", errors="replace") for item in cmdline if item]
    if not arguments or Path(arguments[0]).name != "google-chrome-stable" or "about:blank" not in arguments:
        raise PostFinalRebootAcceptanceError("Kørende browser matcher ikke canonical Chrome kiosk-runtime")

    marker = _read_json_object(DISPLAY_BOOT_MARKER_PATH, "Browser boot-marker")
    if marker.get("boot_id") != current_boot:
        raise PostFinalRebootAcceptanceError("Browser boot-marker tilhører ikke det aktuelle boot")
    if marker.get("countdown_reason") != "system_start" or marker.get("countdown_seconds") != EXPECTED_BOOT_COUNTDOWN_SECONDS:
        raise PostFinalRebootAcceptanceError("Browser boot-marker beviser ikke præcis 10 sekunders normal boot-start")
    return kiosk_url


def _kiosk_url_matches(configured: str, actual: str) -> bool:
    try:
        expected = urlsplit(configured)
        observed = urlsplit(actual)
        expected_port = expected.port or (443 if expected.scheme == "https" else 80)
        observed_port = observed.port or (443 if observed.scheme == "https" else 80)
    except ValueError:
        return False
    if (expected.scheme.lower(), (expected.hostname or "").lower(), expected_port) != (
        observed.scheme.lower(), (observed.hostname or "").lower(), observed_port
    ):
        return False
    expected_path = expected.path.rstrip("/") or "/"
    observed_path = observed.path.rstrip("/") or "/"
    if expected_path != observed_path:
        return False
    expected_query = sorted(parse_qsl(expected.query, keep_blank_values=True))
    observed_query = sorted(
        (key, value) for key, value in parse_qsl(observed.query, keep_blank_values=True)
        if key != "_kiosk_refresh"
    )
    return expected_query == observed_query


def _verify_browser_guard(kiosk_url: str) -> None:
    # Reuse the production DevTools transport, but only evaluate a read-only
    # acceptance probe. The running Browser Guard must already have installed
    # its marker/CSS and removed any visible supported consent overlay.
    from . import browser_guard

    tab_payload = browser_guard.get_tabs()
    if tab_payload is None:
        raise PostFinalRebootAcceptanceError("Chrome DevTools er endnu ikke klar til Browser Guard acceptance")
    tabs = [item for item in tab_payload if browser_guard.is_main_page_target(item)]
    if not tabs:
        raise PostFinalRebootAcceptanceError("Browser Guard acceptance fandt ingen main-page target")

    async def probe() -> list[object]:
        return [await browser_guard.evaluate_js(tab, _BROWSER_GUARD_PROBE_JS, "post-reboot-acceptance") for tab in tabs]

    results = asyncio.run(probe())
    matching_kiosk_url = False
    for result in results:
        if not isinstance(result, dict) or result.get("error"):
            raise PostFinalRebootAcceptanceError("Browser Guard acceptance-probe fejlede")
        if result.get("readyState") != "complete":
            raise PostFinalRebootAcceptanceError("Browser-siden er endnu ikke complete")
        if result.get("marker") != browser_guard.VERSION or result.get("css") is not True:
            raise PostFinalRebootAcceptanceError("Browser Guard er ikke observeret aktiv på kiosk-siden")
        if result.get("visibleConsent"):
            raise PostFinalRebootAcceptanceError("Synligt cookie/consent-overlay er observeret efter Browser Guard")
        if _kiosk_url_matches(kiosk_url, str(result.get("href") or "")):
            matching_kiosk_url = True
    if not matching_kiosk_url:
        raise PostFinalRebootAcceptanceError("Kørende kiosk-side matcher ikke den konfigurerede URL")


def _verify_critical_services() -> None:
    failed: list[str] = []
    for unit in CRITICAL_ACTIVE_UNITS:
        result = _run([str(SYSTEMCTL), "is-active", "--quiet", unit], timeout=5.0)
        if result.returncode != 0:
            failed.append(unit)
    if failed:
        raise PostFinalRebootAcceptanceError("Kritiske ClientFlow-units er ikke active: " + ", ".join(failed[:6]))
    environment = _run([
        str(SYSTEMCTL), "show", "clientflow-browser-guard.service",
        "--property=Environment", "--value",
    ], timeout=5.0)
    if environment.returncode != 0 or "CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE=accept" not in environment.stdout.split():
        raise PostFinalRebootAcceptanceError("Browser Guard cookie-mode er ikke verificeret som accept")


def _verify_backend_approved() -> None:
    try:
        credential = DomainCredential.load(Domain.STATUS)
        token = DomainTransport(credential).access_token(force_refresh=True)
    except Exception as exc:
        raise PostFinalRebootAcceptanceError("Backend Approved-status kunne ikke verificeres med status-credential") from exc
    if not token:
        raise PostFinalRebootAcceptanceError("Backend Approved-status returnerede intet domænetoken")


def verify_and_accept() -> dict[str, object]:
    if os.geteuid() != 0:
        raise PostFinalRebootAcceptanceError("Post-final-reboot acceptance kræver root")
    state = _read_state()
    if state is None:
        return {"schema_version": 1, "status": "not_required"}
    if state.get("status") == "accepted":
        return state
    if state.get("status") != "awaiting_post_final_reboot_acceptance":
        raise PostFinalRebootAcceptanceError("Customer handoff-state er ikke pending acceptance")

    current_boot = _boot_id()
    previous_boot = str(state.get("pre_reboot_boot_id") or "").strip()
    if not previous_boot or current_boot == previous_boot:
        raise PostFinalRebootAcceptanceError("Final reboot er endnu ikke observeret")
    if _active_local_kiosk_session() is None:
        raise PostFinalRebootAcceptanceError("Canonical clientflow-kiosk Wayland-session er endnu ikke aktiv på seat0")

    lockdown = lockdown_status()
    if (
        lockdown.get("desired") is True
        and (
            lockdown.get("status") != "applied"
            or not isinstance(lockdown.get("enforcement"), dict)
            or lockdown["enforcement"].get("ok") is not True
        )
    ):
        try:
            lockdown = apply_lockdown()
        except Exception as exc:
            raise PostFinalRebootAcceptanceError(
                "Kiosk lockdown kunne ikke konvergeres efter final reboot"
            ) from exc
    if (
        lockdown.get("desired") is not True
        or lockdown.get("status") != "applied"
        or not isinstance(lockdown.get("enforcement"), dict)
        or lockdown["enforcement"].get("ok") is not True
    ):
        raise PostFinalRebootAcceptanceError("Kiosk lockdown er ikke verificeret applied efter final reboot")

    kiosk_groups = _group_names(KIOSK_USER)
    if kiosk_groups & ADMIN_GROUPS:
        raise PostFinalRebootAcceptanceError("Kiosk-brugeren har administratorgruppe efter final reboot")
    admin_groups = _group_names(ADMIN_USER)
    if not (admin_groups & ADMIN_GROUPS):
        raise PostFinalRebootAcceptanceError("cfadmin mangler administratorgruppe efter final reboot")

    _verify_nautilus_ding_session()
    kiosk_url = _verify_display_runtime(current_boot)
    _verify_critical_services()
    _verify_browser_guard(kiosk_url)
    _verify_backend_approved()

    accepted = dict(state)
    accepted.update({
        "status": "accepted",
        "accepted_boot_id": current_boot,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "kiosk_lockdown_status": "applied",
        "kiosk_session_ready": True,
        "nautilus_ready": True,
        "ding_filemanager_ready": True,
        "account_separation_ready": True,
        "browser_boot_ready": True,
        "browser_boot_countdown_seconds": EXPECTED_BOOT_COUNTDOWN_SECONDS,
        "browser_guard_ready": True,
        "critical_services_ready": True,
        "backend_approved_ready": True,
    })
    atomic_write_json(STATE_PATH, accepted, mode=0o600)
    return accepted


def main() -> int:
    try:
        result = verify_and_accept()
    except (OSError, ValueError, PostFinalRebootAcceptanceError) as exc:
        print(f"CLIENTFLOW_POST_FINAL_REBOOT_ACCEPTANCE_PENDING: {exc}", flush=True)
        return 1
    print(f"CLIENTFLOW_POST_FINAL_REBOOT_ACCEPTANCE_OK: {result.get('status')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
