import AppSnackbar from "../../components/AppSnackbar";
import React, { lazy, Suspense, useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  Container,
  Grid,
  Alert,
  useMediaQuery,
  Typography,
  Chip,
  Stack,
  Button,
  IconButton,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import RefreshIcon from "@mui/icons-material/Refresh";

const ClientDetailsInfoSection = lazy(() => import("./ClientDetailsInfoSection"));
const ClientDetailsActionsSection = lazy(() => import("./ClientDetailsActionsSection"));
const ClientDetailsLivestreamSection = lazy(() => import("./ClientDetailsLivestreamSection"));
const ClientCalendarDialog = lazy(() => import("../calendarpage/ClientCalendarDialog"));
import { compactDarkChipSx } from "../../utils/chipStyles";
import { isPageVisible } from "../../utils/pageVisibility";
import { useAuth } from "../../auth/AuthProvider";

import {
  getChromeStatus,
  getClientflowDeployments,
  clientAction,
  openRemoteDesktop,
} from "../../api";

/*
  ClientDetailsPage.jsx

  Lock-logik — tre lag:

  1. PCA skal være "none" i backend (klienten har modtaget handlingen)

  2. Step-timestamp valideres mod action-starttidspunkt.
     Steps ældre end handlingen ignoreres — de tilhører en forrige handling.

  3. Chrome-step afgør unlock — handlings-specifikt via TERMINAL_STEPS_BY_ACTION.
     Terminal tjekkes ALTID før busy — vigtigt for reboot/shutdown hvor
     system_rebooting/system_shutting_down er i BUSY_CHROME_STEPS (for banneret)
     men skal være terminal for deres respektive actions.

  PROBLEMS DER LØSES:

  A) "start" — chrome_closed_programmatically må ikke være terminal:
       clear_cookies (BUSY) → shutdown_chrome (terminal, ikke busy)
       → watchdog: chrome_closed_programmatically   ← MÅ IKKE UNLOCK
       → countdown (BUSY) → start_chrome (TERMINAL ✓)

  B) "sleep" — chrome_closed_programmatically må ikke være terminal:
       shutdown_chrome → watchdog: chrome_closed_programmatically ← MÅ IKKE UNLOCK
       → countdown (BUSY) → system_sleep (TERMINAL ✓)

  C) "reboot"/"shutdown" — terminal skal tjekkes FØR busy:
       shutdown_chrome → system_rebooting  ← BUSY i sættet men TERMINAL for action
       Uden fix: polling venter 60s timeout fordi BUSY altid vinder.
       Med fix: terminal tjekkes først → unlock korrekt.

  Faktiske step-navne fra chrome_kiosk.py / kiosk_sleep.py / kiosk_wake.py:

  BUSY_CHROME_STEPS (låser knapper + banner i DetailsActionsSection):
    clear_cookies            — rydder cookies
    terminate_chrome         — SIGTERM til Chrome
    kill_chrome              — SIGKILL til Chrome
    countdown                — nedtælling før start eller sleep
    system_reboot_countdown  — nedtælling før reboot efter wake
    system_rebooting         — maskinen genstarter (også terminal for reboot-action)
    system_shutting_down     — maskinen lukker ned (også terminal for shutdown-action)

  FIX: shutdown_chrome er FJERNET fra BUSY_CHROME_STEPS — det er et
  terminal-step (Chrome er færdig med at lukke), ikke et busy-step.
  Tidligere sad polling-løkken fast på "continue" ved shutdown_chrome
  fordi BUSY altid vandt over terminal-tjekket.

  TERMINAL_STEPS_BY_ACTION:
    start    → start_chrome, error
    stop     → chrome_closed_programmatically, chrome_closed_manual, error
    sleep    → system_sleep, error
    wakeup   → system_wake, error
    reboot   → system_rebooting, error
    shutdown → system_shutting_down, error
*/

const CHROME_STATUS_ACTIVE_POLL_MS = 1000;
const CHROME_STATUS_IDLE_POLL_MS = 5000;
const CHROME_STATUS_HIDDEN_CHECK_MS = 1000;
const ACTION_POLL_MS        = 1500;
const CLIENTFLOW_DEPLOYMENT_POLL_MS = 2500;
const CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES = new Set([
  "authorized", "downloading", "verified", "staged", "activating", "health_check", "rolling_back",
]);

function SectionLoadingFallback({ label }) {
  return (
    <Box
      role="status"
      aria-live="polite"
      sx={{
        minHeight: 120,
        display: "grid",
        placeItems: "center",
        color: "rgba(203,213,225,0.82)",
        fontSize: "0.9rem",
      }}
    >
      {label}
    </Box>
  );
}

const CHROME_TRUTH_STOPPED_STEPS = new Set([
  "chrome_closed_programmatically",
  "chrome_closed_manual",
  "shutdown_chrome",
  "kill_chrome",
  "display_sleep",
  "display_sleep_complete",
  "display_wake",
  "display_wake_complete",
  "system_sleep",
  "system_sleep_complete",
  "system_wake",
  "system_wake_complete",
  "system_rebooting",
  "system_shutting_down",
]);

const CHROME_TRUTH_RUNNING_STEPS = new Set([
  "start_chrome",
  "chrome_opened_manual",
]);

function inferChromeRunningFromStep(stepName, fallbackValue = null) {
  const s = String(stepName || "").trim().toLowerCase();
  if (CHROME_TRUTH_RUNNING_STEPS.has(s)) return true;
  if (CHROME_TRUTH_STOPPED_STEPS.has(s)) return false;
  return fallbackValue;
}

const ACTION_POLL_MAX_MS    = 60_000;
const ACTION_MIN_LOCK_MS    = 2000;
const ACTION_NULL_STEP_MS   = 8000;

// FIX: shutdown_chrome er fjernet — det er terminal, ikke busy.
// Skal matche BUSY_CHROME_STEPS i DetailsActionsSection.jsx.
const BUSY_CHROME_STEPS = new Set([
  "clear_cookies",
  "terminate_chrome",
  "kill_chrome",
  "starting_chrome",
  "countdown",
  "display_sleep_countdown",
  "system_reboot_countdown",
  "system_rebooting",
  "system_shutting_down",
]);

function chromeStatusNeedsFastPolling(data) {
  const pendingAction = String(data?.pending_chrome_action || "none").trim().toLowerCase();
  const state = String(data?.state || "").trim().toLowerCase();
  const step = String(data?.chrome_step || data?.step?.step || "").trim().toLowerCase();
  const updateStatus = String(data?.ubuntu_update_status || "").trim().toLowerCase();
  const localManagementStatus = String(data?.local_management_status || "").trim().toLowerCase();

  return (
    (pendingAction && pendingAction !== "none") ||
    data?.pending_reboot === true ||
    data?.pending_shutdown === true ||
    data?.pending_os_update === true ||
    ["wakeup", "rebooting", "updating"].includes(state) ||
    BUSY_CHROME_STEPS.has(step) ||
    updateStatus === "requested" ||
    updateStatus === "installing" ||
    localManagementStatus === "pending" ||
    localManagementStatus === "running"
  );
}

/*
  Handlings-specifikke terminal steps.

  start:
    Venter KUN på start_chrome.
    chrome_closed_programmatically skrives af watchdog midt i sekvensen
    (når eksisterende Chrome dræbes som forberedelse til genstart) — må
    ikke terminere polling, ellers låses knapper op under countdown.

  stop:
    chrome_closed_programmatically og chrome_closed_manual er korrekte
    terminal steps — det er præcis hvad watchdog skriver når Chrome stoppes.

  sleep:
    Venter KUN på system_sleep.
    chrome_closed_programmatically skrives af watchdog FØR countdown i
    sleep-sekvensen — må ikke terminere polling:
      shutdown_chrome → watchdog: chrome_closed_programmatically
      → countdown (BUSY) → system_sleep (TERMINAL)

  wakeup:
    system_wake er terminal. Maskinen rebootes umiddelbart efter.

  reboot:
    system_rebooting er terminal for reboot — maskinen er ved at genstarte.
    NB: system_rebooting er også i BUSY_CHROME_STEPS (for banneret i
    DetailsActionsSection), men terminal tjekkes FØR busy i polling-loopen.

  shutdown:
    system_shutting_down er terminal for shutdown — samme princip som reboot.
*/
const TERMINAL_STEPS_BY_ACTION = {
  start:    new Set(["start_chrome", "error"]),
  stop:     new Set(["chrome_closed_programmatically", "chrome_closed_manual", "shutdown_chrome", "error"]),
  sleep:    new Set(["system_sleep", "system_sleep_complete", "display_sleep", "display_sleep_complete", "error"]),
  wakeup:   new Set(["system_wake", "system_wake_complete", "display_wake", "display_wake_complete", "error"]),
  reboot:   new Set(["system_rebooting", "error"]),
  shutdown: new Set(["system_shutting_down", "error"]),
  reset_browser: new Set(["start_chrome", "error"]),
};

// Fallback hvis action ikke kendes
const DEFAULT_TERMINAL_STEPS = new Set([
  "start_chrome",
  "chrome_closed_programmatically",
  "chrome_closed_manual",
  "shutdown_chrome",
  "system_sleep",
  "system_sleep_complete",
  "display_sleep",
  "display_sleep_complete",
  "system_wake",
  "system_wake_complete",
  "display_wake",
  "display_wake_complete",
  "error",
]);

const DISPLAY_RESOLUTION_LIVE_FIELDS = [
  "display_power",
  "display_resolution_preset",
  "display_resolution_mode",
  "display_resolution_width",
  "display_resolution_height",
  "display_resolution_refresh_rate",
  "display_resolution_rotation",
  "display_resolution_action",
  "display_resolution_updated_at",
  "display_resolution_current_output",
  "display_resolution_current_width",
  "display_resolution_current_height",
  "display_resolution_current_refresh_rate",
  "display_resolution_status",
  "display_resolution_error",
  "display_resolution_last_applied_at",
  "display_detected_outputs",
  "display_detected_updated_at",
];

const DETAIL_HOT_FIELDS = [
  // Stable detail/configuration values are already loaded by /chrome-status
  // for authorization. Carry them on the same hot response so Configuration
  // and Diagnostics do not need parallel full-client polling loops.
  "name",
  "locality",
  "status",
  "organization_id",
  "machine_id",
  "kiosk_url",
  "browser_refresh_interval_sec",
  "service_clientflow_status",
  "service_calendar_status",
  "service_browser_guard_status",
  "service_remote_terminal_status",
  "service_admin_terminal_status",
  "service_remote_desktop_status",
  "service_livestream_status",
  "service_selfupdate_status",
  "last_boot_at",
  "last_boot_id",
  "last_power_event",
  "last_power_event_at",
  "last_power_event_source",
  "last_reboot_started_at",
  "last_shutdown_started_at",
  "livestream_last_segment",
  "livestream_last_error",
  "desktop_lockdown_enabled",
  "desktop_lockdown_status",
  "desktop_lockdown_message",
  "desktop_lockdown_updated_at",
  "desktop_lockdown_last_applied_at",
];

const NETWORK_LIVE_FIELDS = [
  "network_status",
  "network_status_message",
  "network_status_color",
  "network_has_connection",
  "diagnostics_updated_at",
  "system_timezone",
  "ntp_enabled",
  "ntp_synchronized",
  "client_time_utc",
  "clock_drift_seconds",
  "time_sync_status",
  "time_sync_message",
  "active_network_type",
  "active_network_interface",
  "active_network_ip",
  "active_network_mac",
  "wifi_ip_address",
  "wifi_mac_address",
  "lan_ip_address",
  "lan_mac_address",
];

const UPDATE_LIVE_FIELDS = [
  // Software-versioner skal følge samme live-feed som update-status.
  // /chrome-status polles hvert sekund, så ClientDetailsInfoSection og
  // ActionsSection ikke hænger på den oprindelige client-prop efter update.
  "client_version",
  "client_version_patch",
  "client_version_updated_at",
  "ubuntu_version",
  "pending_reboot",
  "pending_shutdown",
  "pending_os_update",
  "ubuntu_updates_available",
  "service_ubuntu_update_status",
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
  // Local-management is projected by the same System batch that powers the
  // hot read; carrying it here removes the separate 2-second DB poll.
  "local_management_action",
  "local_management_request_id",
  "local_management_desired_hostname",
  "local_management_status",
  "local_management_message",
  "local_management_requested_at",
  "local_management_started_at",
  "local_management_finished_at",
  "local_management_error",
];

function pickLiveFields(data, fields) {
  if (!data || typeof data !== "object") return {};

  return fields.reduce((acc, field) => {
    if (Object.prototype.hasOwnProperty.call(data, field)) {
      acc[field] = data[field];
    }
    return acc;
  }, {});
}

function pickDetailHotFields(data) {
  return pickLiveFields(data, DETAIL_HOT_FIELDS);
}

function pickDisplayResolutionFields(data) {
  return pickLiveFields(data, DISPLAY_RESOLUTION_LIVE_FIELDS);
}

function pickNetworkFields(data) {
  return pickLiveFields(data, NETWORK_LIVE_FIELDS);
}

function pickUpdateFields(data) {
  return pickLiveFields(data, UPDATE_LIVE_FIELDS);
}

function normalizeNetworkStatus(value) {
  return String(value || "").trim().toLowerCase();
}

function getNetworkStatusMessage(client) {
  const explicit = client?.network_status_message;
  if (explicit) return explicit;
  const status = normalizeNetworkStatus(client?.network_status);
  if (["no_network", "missing", "disconnected"].includes(status)) return "Seneste diagnostik registrerede ingen aktiv netværksforbindelse";
  if (status === "unknown") return "Netværksdiagnostik ukendt";
  return null;
}

function isNetworkUnavailable(client) {
  const status = normalizeNetworkStatus(client?.network_status);
  return client?.network_has_connection === false || ["no_network", "missing", "disconnected"].includes(status);
}

function presenceFetchFailed(previous) {
  return {
    ...(previous || {}),
    is_online: false,
    status: {
      ...(previous?.status || {}),
      domain: "status",
      is_online: false,
      reason: "presence_fetch_failed",
    },
    display: {
      ...(previous?.display || {}),
      domain: "display",
      is_online: false,
      reason: "presence_fetch_failed",
    },
    system: {
      ...(previous?.system || {}),
      domain: "system",
      is_online: false,
      reason: "presence_fetch_failed",
    },
  };
}

function resolveChromeStepPayload(data) {
  if (!data || typeof data !== "object") {
    return { hasStepField: false, stepName: null, stepTimestamp: null };
  }

  const latestStepFromArray = Array.isArray(data.steps) && data.steps.length > 0
    ? data.steps[data.steps.length - 1]
    : null;

  const hasStepField =
    Object.prototype.hasOwnProperty.call(data, "chrome_step") ||
    Object.prototype.hasOwnProperty.call(data, "last_chrome_step") ||
    Object.prototype.hasOwnProperty.call(data, "step") ||
    Array.isArray(data.steps);

  const stepName =
    data?.step?.step ??
    data?.chrome_step ??
    data?.last_chrome_step ??
    latestStepFromArray?.step ??
    null;

  const stepTimestamp =
    data?.step?.timestamp ??
    data?.chrome_step_timestamp ??
    data?.chrome_last_updated ??
    latestStepFromArray?.timestamp ??
    null;

  return { hasStepField, stepName, stepTimestamp };
}


function formatDashboardDateTime(value, withSeconds = false) {
  if (!value) return "ukendt";
  const raw = String(value);
  const d = new Date(raw.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw}Z`);
  if (Number.isNaN(d.getTime())) return "ukendt";
  return new Intl.DateTimeFormat("da-DK", {
    timeZone: "Europe/Copenhagen",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined,
    hour12: false,
  }).format(d);
}

function normalizePowerEvent(value) {
  return String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function formatPowerEventLabel(client) {
  if (!client) return null;

  const event = normalizePowerEvent(client.last_power_event);
  const source = normalizePowerEvent(client.last_power_event_source);
  const at = client.last_power_event_at || client.last_boot_at || client.last_reboot_started_at || client.last_shutdown_started_at;
  const time = at ? formatDashboardDateTime(at) : null;

  const sourceLabel = source === "backend"
    ? "backend"
    : source === "calendar"
    ? "kalender"
    : source === "local"
    ? "lokal"
    : source === "client"
    ? "klient"
    : source === "detected"
    ? "registreret"
    : source || null;

  let label = null;
  if (["reboot_started", "reboot_requested"].includes(event)) label = "Genstart startet";
  else if (event === "reboot_completed") label = "Genstart fuldført";
  else if (["shutdown_started", "shutdown_requested"].includes(event)) label = "Nedlukning startet";
  else if (event === "boot_after_shutdown") label = "Boot efter nedlukning";
  else if (["boot_completed", "boot_detected", "boot"].includes(event)) label = "Boot registreret";
  else if (event) label = event.replaceAll("_", " ");
  else if (client.last_boot_at) label = "Boot registreret";

  if (!label) return null;
  const pieces = [label];
  if (time) pieces.push(time);
  if (sourceLabel) pieces.push(sourceLabel);
  return pieces.join(" · ");
}

function powerEventColor(client) {
  const event = normalizePowerEvent(client?.last_power_event);
  if (event.includes("shutdown")) return "warning";
  if (event.includes("reboot")) return "warning";
  if (event.includes("boot")) return "info";
  return "default";
}

function formatDashboardUptime(value) {
  if (value === null || value === undefined || value === "") return "ukendt";
  const n = Number.parseInt(String(value), 10);
  if (!Number.isFinite(n) || n < 0) return String(value);
  const days = Math.floor(n / 86400);
  const hours = Math.floor((n % 86400) / 3600);
  const mins = Math.floor((n % 3600) / 60);
  if (days > 0) return `${days} d. ${hours} t.`;
  if (hours > 0) return `${hours} t. ${mins} min.`;
  return `${mins} min.`;
}

function formatUbuntuMetric(client) {
  const raw = client?.ubuntu_updates_available;
  const count = Number.parseInt(String(raw ?? ""), 10);
  if (client?.pending_os_update || client?.state === "updating") return "Opdaterer";
  if (!Number.isFinite(count) || count < 0) return "ukendt";
  return count === 0 ? "Ingen" : `${count} klar`;
}

function normalizeDashboardStep(step) {
  const s = String(step || "").trim().toLowerCase();
  if (!s) return null;
  const labels = {
    clear_cookies: "Rydder cookies",
    terminate_chrome: "Lukker browser",
    kill_chrome: "Tvangslukker browser",
    shutdown_chrome: "Browser lukket",
    countdown: null,
    display_sleep_countdown: "Skærm slukkes snart",
    system_reboot_countdown: "Genstarter snart",
    system_rebooting: "Genstarter maskine",
    system_shutting_down: "Lukker maskine ned",
    start_chrome: "Browser startet",
    chrome_closed_programmatically: "Browser lukket",
    chrome_closed_manual: "Browser lukket manuelt",
    system_sleep: "Dvale",
    system_sleep_complete: "Dvale",
    display_sleep: "Skærm slukkes",
    display_sleep_complete: "Skærm slukket",
    system_wake: "Vækker klient",
    system_wake_complete: "Klient vågen",
    display_wake: "Tænder skærm",
    display_wake_complete: "Skærm tændt",
    error: "Fejl",
  };
  return labels[s] || s.replaceAll("_", " ");
}

function resolveCssColor(theme, color, fallback = "rgba(148, 163, 184, 0.85)") {
  if (!color) return fallback;

  if (typeof color !== "string") return fallback;

  const trimmed = color.trim();
  if (!trimmed) return fallback;

  if (/^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$/.test(trimmed) || /^rgba?\(/i.test(trimmed)) {
    return trimmed;
  }

  const lower = trimmed.toLowerCase();

  const namedColors = {
    green: "#43a047",
    success: "#43a047",
    red: "#e53935",
    error: "#e53935",
    yellow: "#fbc02d",
    warning: "#f59e0b",
    orange: "#f59e0b",
    blue: "#1976d2",
    info: "#0288d1",
    primary: "#1976d2",
    secondary: "#7c3aed",
    grey: "#64748b",
    gray: "#64748b",
    black: "#000000",
    white: "#ffffff",
  };

  if (namedColors[lower]) return namedColors[lower];

  if (lower.includes(".")) {
    const [paletteKey, shade] = lower.split(".");
    const paletteValue = theme.palette?.[paletteKey];
    if (paletteValue?.[shade]) return paletteValue[shade];
    if (paletteValue?.main) return paletteValue.main;
  }

  const paletteValue = theme.palette?.[lower];
  if (paletteValue?.main) return paletteValue.main;
  if (typeof paletteValue === "string") return paletteValue;

  return fallback;
}

function hexToRgba(hex, opacity) {
  const raw = String(hex || "").trim().replace(/^#/, "");
  if (![3, 6, 8].includes(raw.length)) return null;

  const normalized = raw.length === 3
    ? raw.split("").map((ch) => ch + ch).join("")
    : raw.slice(0, 6);

  const value = Number.parseInt(normalized, 16);
  if (!Number.isFinite(value)) return null;

  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function rgbToRgba(value, opacity) {
  const raw = String(value || "").trim();
  const match = raw.match(/^rgba?\(([^)]+)\)$/i);
  if (!match) return null;

  const parts = match[1].split(",").map((part) => part.trim());
  if (parts.length < 3) return null;

  const [r, g, b] = parts;
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function safeAlpha(theme, color, opacity, fallback = "rgba(148, 163, 184, 0.85)") {
  const resolved = resolveCssColor(theme, color, fallback);

  if (String(resolved).trim().startsWith("#")) {
    return hexToRgba(resolved, opacity) || fallback;
  }

  if (/^rgba?\(/i.test(String(resolved).trim())) {
    return rgbToRgba(resolved, opacity) || fallback;
  }

  const fallbackResolved = resolveCssColor(theme, fallback, "rgba(148, 163, 184, 0.85)");
  if (String(fallbackResolved).trim().startsWith("#")) {
    return hexToRgba(fallbackResolved, opacity) || "rgba(148, 163, 184, 0.85)";
  }
  if (/^rgba?\(/i.test(String(fallbackResolved).trim())) {
    return rgbToRgba(fallbackResolved, opacity) || fallbackResolved;
  }

  return "rgba(148, 163, 184, 0.85)";
}

function StatusDot({ color = "rgba(148, 163, 184, 0.85)" }) {
  const theme = useTheme();
  const resolvedColor = resolveCssColor(theme, color);

  return (
    <Box
      component="span"
      sx={{
        width: 8,
        height: 8,
        borderRadius: "50%",
        bgcolor: resolvedColor,
        boxShadow: `0 0 0 4px ${safeAlpha(theme, resolvedColor, 0.16)}`,
        flex: "0 0 auto",
      }}
    />
  );
}

function DashboardChip({ label, color = "default", variant = "outlined" }) {
  return (
    <Chip
      size="small"
      variant={variant}
      label={label}
      sx={compactDarkChipSx(color, {
        letterSpacing: 0.1,
        maxWidth: "100%",
        "& .MuiChip-label": { overflow: "hidden", textOverflow: "ellipsis" },
      })}
    />
  );
}

function MetricTile({ label, value, helper, tone = "default", dark = false }) {
  const theme = useTheme();
  const palette = tone === "success"
    ? theme.palette.success
    : tone === "warning"
    ? theme.palette.warning
    : tone === "error"
    ? theme.palette.error
    : tone === "info"
    ? theme.palette.info
    : theme.palette.primary;

  return (
    <Box
      sx={{
        minWidth: 0,
        p: 1.4,
        borderRadius: 2,
        border: "1px solid",
        borderColor: dark ? safeAlpha(theme, palette.main, tone === "default" ? 0.18 : 0.34) : safeAlpha(theme, palette.main, tone === "default" ? 0.12 : 0.22),
        bgcolor: dark ? safeAlpha(theme, palette.main, tone === "default" ? 0.07 : 0.13) : safeAlpha(theme, palette.main, tone === "default" ? 0.035 : 0.075),
        boxShadow: dark ? "inset 0 1px 0 rgba(255,255,255,0.04)" : "none",
      }}
    >
      <Typography
        variant="caption"
        sx={{
          fontWeight: 900,
          textTransform: "uppercase",
          letterSpacing: 0.55,
          color: dark ? "rgba(203,213,225,0.74)" : "text.secondary",
        }}
      >
        {label}
      </Typography>
      <Typography
        variant="body1"
        sx={{
          mt: 0.25,
          fontWeight: 900,
          color: dark ? "#f8fafc" : "text.primary",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {value || "ukendt"}
      </Typography>
      {helper && (
        <Typography
          variant="caption"
          sx={{
            display: "block",
            mt: 0.25,
            color: dark ? "rgba(203,213,225,0.62)" : "text.secondary",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {helper}
        </Typography>
      )}
    </Box>
  );
}

function glassPanelSx(theme, isMobile = false) {
  return {
    borderRadius: isMobile ? 3 : 4,
    overflow: "hidden",
    background: "linear-gradient(180deg, rgba(15,23,42,0.86), rgba(15,23,42,0.66))",
    border: "1px solid rgba(148,163,184,0.18)",
    boxShadow: "0 24px 70px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.04)",
    backdropFilter: "blur(18px)",
    color: "#f8fafc",
    "& .MuiTypography-root": {
      color: "inherit",
    },
    "& .MuiTypography-colorTextSecondary": {
      color: "rgba(203,213,225,0.68)",
    },
    "& .MuiCard-root": {
      background: "rgba(15,23,42,0.58)",
      border: "1px solid rgba(148,163,184,0.14)",
      boxShadow: "none",
      color: "#f8fafc",
    },
    "& .MuiTableCell-root": {
      color: "rgba(248,250,252,0.92)",
      borderColor: "rgba(148,163,184,0.12)",
    },
    "& .MuiButton-outlined": {
      borderColor: "rgba(148,163,184,0.26)",
      color: "rgba(248,250,252,0.94)",
    },
    "& .MuiButton-contained": {
      boxShadow: "0 14px 34px rgba(0,0,0,0.22)",
    },
    "& .MuiTabs-indicator": {
      height: 3,
      borderRadius: 999,
    },
    "& .MuiTab-root": {
      color: "rgba(203,213,225,0.72)",
    },
    "& .Mui-selected": {
      color: `${theme.palette.info.light} !important`,
    },
  };
}

function ControlRoomTopbar({ client, clientOnline, networkUnavailable, networkMessage, liveChromeStatus, clientState, refreshing, onRefresh, onBack, isMobile }) {
  const theme = useTheme();
  const clientName = client?.name || client?.client_name || "Ukendt infoskærm";
  const organizationName = client?.organization_name || client?.organization?.name || "";
  const location = client?.locality || client?.location || "Ingen lokation";
  const powerEventLabel = formatPowerEventLabel(client);

  return (
    <Box
      sx={{
        ...glassPanelSx(theme, isMobile),
        p: isMobile ? 1.25 : 1.75,
        display: "flex",
        alignItems: isMobile ? "stretch" : "center",
        justifyContent: "space-between",
        gap: 1.5,
        flexDirection: isMobile ? "column" : "row",
      }}
    >
      <Stack
        direction="row"
        spacing={1.25}
        sx={{
          alignItems: "center",
          minWidth: 0
        }}>
        <IconButton
          size="small"
          onClick={onBack}
          sx={{
            color: "rgba(248,250,252,0.92)",
            border: "1px solid rgba(148,163,184,0.20)",
            bgcolor: "rgba(15,23,42,0.42)",
          }}
        >
          <ArrowBackIcon fontSize="small" />
        </IconButton>

        <Box sx={{
          minWidth: 0
        }}>
          <Typography variant={isMobile ? "h6" : "h5"} sx={{ fontWeight: 950, lineHeight: 1.08, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {clientName}
          </Typography>
          <Typography variant="body2" sx={{ color: "rgba(203,213,225,0.68)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {[organizationName, location].filter(Boolean).join(" · ")}
          </Typography>
        </Box>
      </Stack>
      <Stack
        direction="row"
        spacing={1}
        useFlexGap
        sx={{
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: isMobile ? "flex-start" : "flex-end"
        }}>
        <DashboardChip dark label={clientOnline ? "Online" : "Offline"} color={clientOnline ? "success" : "error"} variant="filled" />
        <DashboardChip dark label={clientState || "ukendt"} color={clientState === "normal" ? "success" : "warning"} />
        {powerEventLabel && (
          <DashboardChip dark label={powerEventLabel} color={powerEventColor(client)} />
        )}
        <DashboardChip dark label={clientOnline ? (liveChromeStatus || "Browser ukendt") : "Browser offline"} color={clientOnline ? "info" : "default"} />
        {networkUnavailable && (
          <DashboardChip dark label={`Netværk: ${networkMessage || "diagnostik melder fejl"}`} color="error" />
        )}
        <Button
          size="small"
          variant="outlined"
          startIcon={<RefreshIcon />}
          onClick={onRefresh}
          disabled={!!refreshing}
          sx={{
            borderRadius: 999,
            textTransform: "none",
            fontWeight: 900,
            color: "rgba(248,250,252,0.94)",
            borderColor: "rgba(148,163,184,0.25)",
          }}
        >
          {refreshing ? "Opdaterer…" : "Opdater"}
        </Button>
      </Stack>
    </Box>
  );
}

function SectionTitle({ eyebrow, title, description, dark = true }) {
  return (
    <Box sx={{ mb: 1.15 }}>
      {eyebrow && (
        <Typography variant="overline" sx={{ color: dark ? "rgba(125,211,252,0.76)" : "text.secondary", fontWeight: 900, letterSpacing: 0.9 }}>
          {eyebrow}
        </Typography>
      )}
      <Typography variant="h6" sx={{ fontWeight: 950, lineHeight: 1.1, color: dark ? "#f8fafc" : "text.primary" }}>
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" sx={{ color: dark ? "rgba(203,213,225,0.66)" : "text.secondary", mt: 0.25 }}>
          {description}
        </Typography>
      )}
    </Box>
  );
}



export default function ClientDetailsPage({
  client,
  refreshing,
  handleRefresh,
  silentRefresh,
  silentRefreshAll,
  onCancelActionPollRef,
  markedDays,
  calendarLoading,
  streamKey,
  onRestartStream,
  showSnackbar: showSnackbarProp,
}) {
  const theme    = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const navigate = useNavigate();
  const { user } = useAuth();
  const isSuperadmin = user?.role === "superadmin";

  // --- Lokal snackbar (fallback) ---
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: "",
    severity: "success",
  });

  const showSnackbar = useCallback(
    (opts) => {
      if (typeof showSnackbarProp === "function") {
        showSnackbarProp(opts);
      } else {
        setSnackbar({
          open: true,
          message: opts?.message ?? "",
          severity: opts?.severity ?? "success",
        });
      }
    },
    [showSnackbarProp]
  );

  const handleCloseSnackbar = useCallback(() => {
    setSnackbar((prev) => ({ ...prev, open: false }));
  }, []);

  // --- Kalender dialog ---
  const [calendarDialogOpen, setCalendarDialogOpen] = useState(false);

  // ---------------------------------------------------------------------------
  // Live chrome-status — opdateres hvert 1s uden full re-render
  // ---------------------------------------------------------------------------
  const [liveChromeStatus, setLiveChromeStatus] = useState(
    client?.chrome_status ?? null
  );
  const [liveChromeColor, setLiveChromeColor] = useState(
    client?.chrome_color ?? null
  );
  const [liveChromeRunning, setLiveChromeRunning] = useState(
    typeof client?.chrome_running === "boolean"
      ? client.chrome_running
      : typeof client?.chromeRunning === "boolean"
      ? client.chromeRunning
      : null
  );
  const liveChromeRunningRef = useRef(
    typeof client?.chrome_running === "boolean"
      ? client.chrome_running
      : typeof client?.chromeRunning === "boolean"
      ? client.chromeRunning
      : null
  );
  const [liveBrowserRequested, setLiveBrowserRequested] = useState(
    typeof client?.browser_requested === "boolean" ? client.browser_requested : null
  );
  const [liveStep, setLiveStep]      = useState(client?.chrome_step ?? null);
  const liveStepRef                  = useRef(client?.chrome_step ?? null);
  const liveStepTimestampRef         = useRef(client?.chrome_last_updated ?? null);

  // Stable detail/configuration data piggybacks on the same /chrome-status
  // request. This preserves 5-second idle freshness while removing separate
  // 10/15-second full-client DB polling from Diagnostics/Configuration.
  const [liveDetailHotFields, setLiveDetailHotFields] = useState(() =>
    pickDetailHotFields(client)
  );

  // Display-opløsning kommer med i /chrome-status, så UI'et kan følge
  // backend-/klientændringer uden at vente på manuel eller silent refresh.
  const [liveDisplayResolution, setLiveDisplayResolution] = useState(() =>
    pickDisplayResolutionFields(client)
  );

  const [liveNetworkStatus, setLiveNetworkStatus] = useState(() =>
    pickNetworkFields(client)
  );

  const [liveUpdateFields, setLiveUpdateFields] = useState(() =>
    pickUpdateFields(client)
  );
  // ClientFlow deployment state has one owner at the common parent. Both the
  // Actions and Software controls consume the same snapshot, so they never
  // poll the deployment table independently. Inactive state is revalidated on
  // mount/focus only; an active deployment gets one bounded 2.5-second poll.
  const [clientflowDeployment, setClientflowDeployment] = useState(null);
  const deploymentRefreshInFlightRef = useRef(false);

  const refreshClientflowDeployment = useCallback(async () => {
    if (!client?.id || !isSuperadmin || deploymentRefreshInFlightRef.current) return null;
    deploymentRefreshInFlightRef.current = true;
    try {
      const rows = await getClientflowDeployments(client.id, { limit: 1 });
      const latest = Array.isArray(rows) && rows.length ? rows[0] : null;
      setClientflowDeployment(latest);
      return latest;
    } catch {
      // A transient read failure must not fabricate "no active deployment".
      // Keep the last known snapshot; backend action endpoints still enforce
      // the durable no-concurrent-deployment invariant.
      return null;
    } finally {
      deploymentRefreshInFlightRef.current = false;
    }
  }, [client?.id, isSuperadmin]);

  useEffect(() => {
    if (!client?.id || !isSuperadmin) {
      setClientflowDeployment(null);
      return undefined;
    }
    // A client navigation must never carry another client's deployment lock.
    setClientflowDeployment(null);
    refreshClientflowDeployment();

    const refreshWhenVisible = () => {
      if (isPageVisible()) refreshClientflowDeployment();
    };
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [client?.id, isSuperadmin, refreshClientflowDeployment]);

  const clientflowDeploymentState = String(clientflowDeployment?.state || "").trim().toLowerCase();
  const clientflowDeploymentActive = CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES.has(clientflowDeploymentState);

  useEffect(() => {
    if (!client?.id || !isSuperadmin || !clientflowDeploymentActive) return undefined;
    const timer = window.setInterval(refreshClientflowDeployment, CLIENTFLOW_DEPLOYMENT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [client?.id, isSuperadmin, clientflowDeploymentActive, refreshClientflowDeployment]);
  // Action-confirmation genbruger den allerede eksisterende 1-sekunds hot poll
  // i stedet for at starte en ekstra full-client DB poll hvert 1,5 sekund.
  // receivedAt=0 betyder, at initial-snapshot aldrig må bekræfte en ny handling.
  const hotPollObservationRef = useRef({
    receivedAt: 0,
    pendingChromeAction: String(client?.pending_chrome_action ?? "none").toLowerCase(),
    pendingReboot: client?.pending_reboot === true,
    pendingShutdown: client?.pending_shutdown === true,
    state: client?.state ?? null,
  });
  const hotPollFastUntilRef = useRef(0);
  const hotPollWakeRef = useRef(null);

  // v7.1.34: Livestream-status skal følge den hurtige /chrome-status polling.
  // Ellers kan Start kiosk være låst af et stale initialt client-snapshot,
  // selvom livestream allerede er stoppet lokalt/backend.
  const [liveLivestreamStatus, setLiveLivestreamStatus] = useState(client?.livestream_status ?? null);
  const [liveLivestreamProcessStatus, setLiveLivestreamProcessStatus] = useState(client?.livestream_process_status ?? null);
  const [liveLivestreamDesiredState, setLiveLivestreamDesiredState] = useState(client?.livestream_desired_state ?? "stopped");
  const [liveLivestreamStopReason, setLiveLivestreamStopReason] = useState(client?.livestream_stop_reason ?? null);

  // ---------------------------------------------------------------------------
  // Lokal pending_chrome_action + state
  // ---------------------------------------------------------------------------
  const [localPendingAction, setLocalPendingAction] = useState(
    client?.pending_chrome_action ?? "none"
  );
  const [localClientState, setLocalClientState] = useState(
    client?.state ?? "normal"
  );
  const [localOsUpdateBusy, setLocalOsUpdateBusy] = useState(false);
  const localOsUpdateBusyTimerRef = useRef(null);

  useEffect(() => {
    setLocalPendingAction(client?.pending_chrome_action ?? "none");
    setLocalClientState(client?.state ?? "normal");
  }, [client?.pending_chrome_action, client?.state]);

  // ---------------------------------------------------------------------------
  // Dynamisk oppetid
  // ---------------------------------------------------------------------------
  const [uptime, setUptime] = useState(null);
  const uptimeBaseRef = useRef(null);
  const uptimeFetchRef = useRef(null);
  const [livePresence, setLivePresence] = useState(client?.presence ?? null);

  useEffect(() => {
    if (client?.uptime != null) {
      const parsed = parseInt(String(client.uptime), 10);
      if (!isNaN(parsed) && parsed >= 0) {
        uptimeBaseRef.current  = parsed;
        uptimeFetchRef.current = Date.now();
        setUptime(parsed);
      }
    }
    setLivePresence(client?.presence ?? null);
    if (client?.chrome_status != null) setLiveChromeStatus(client.chrome_status);
    if (client?.chrome_color != null)  setLiveChromeColor(client.chrome_color);
    if (client?.chrome_step !== undefined) {
      setLiveStep(client.chrome_step ?? null);
      liveStepRef.current = client.chrome_step ?? null;
      liveStepTimestampRef.current = client.chrome_last_updated ?? null;
    }
    if (typeof client?.chrome_running === "boolean") {
      liveChromeRunningRef.current = client.chrome_running;
      setLiveChromeRunning(client.chrome_running);
    } else if (typeof client?.chromeRunning === "boolean") {
      liveChromeRunningRef.current = client.chromeRunning;
      setLiveChromeRunning(client.chromeRunning);
    }
    if (typeof client?.browser_requested === "boolean") {
      setLiveBrowserRequested(client.browser_requested);
    } else {
      setLiveBrowserRequested(null);
    }
    setLiveDetailHotFields(pickDetailHotFields(client));
    setLiveDisplayResolution(pickDisplayResolutionFields(client));
    setLiveNetworkStatus(pickNetworkFields(client));
    setLiveUpdateFields(pickUpdateFields(client));
    hotPollObservationRef.current = {
      receivedAt: 0,
      pendingChromeAction: String(client?.pending_chrome_action ?? "none").toLowerCase(),
      pendingReboot: client?.pending_reboot === true,
      pendingShutdown: client?.pending_shutdown === true,
      state: client?.state ?? null,
    };
    if (client?.livestream_status !== undefined) setLiveLivestreamStatus(client.livestream_status ?? null);
    if (client?.livestream_process_status !== undefined) setLiveLivestreamProcessStatus(client.livestream_process_status ?? null);
    if (client?.livestream_desired_state !== undefined) setLiveLivestreamDesiredState(client.livestream_desired_state ?? "stopped");
    if (client?.livestream_stop_reason !== undefined) setLiveLivestreamStopReason(client.livestream_stop_reason ?? null);
  }, [client]);

  useEffect(() => {
    if (uptimeBaseRef.current == null || uptimeFetchRef.current == null) return;
    const interval = setInterval(() => {
      const elapsed = Math.round((Date.now() - uptimeFetchRef.current) / 1000);
      setUptime(uptimeBaseRef.current + elapsed);
    }, 1000);
    return () => clearInterval(interval);
  }, [client?.id]);

  // ---------------------------------------------------------------------------
  // Canonical presence rides on the existing /chrome-status hot poll. The
  // backend evaluates the same Status/Display/System authority server-side, so
  // a second 5-second HTTP/DB poll would only duplicate work.
  // ---------------------------------------------------------------------------
  // ---------------------------------------------------------------------------
  // Chrome-status polling — adaptive: 1s while active, 5s while stable.
  // ---------------------------------------------------------------------------
  const mountedRef = useRef(true);

  useEffect(() => {
    if (!client?.id) return;
    mountedRef.current = true;
    let cancelled = false;
    let nextPollMs = CHROME_STATUS_ACTIVE_POLL_MS;

    const waitForNextPoll = (delay) =>
      new Promise((resolve) => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timerId);
          if (hotPollWakeRef.current === finish) hotPollWakeRef.current = null;
          resolve();
        };
        const timerId = window.setTimeout(finish, delay);
        hotPollWakeRef.current = finish;
      });

    const wakeWhenVisible = () => {
      if (isPageVisible() && typeof hotPollWakeRef.current === "function") {
        hotPollWakeRef.current();
      }
    };
    window.addEventListener("focus", wakeWhenVisible);
    document.addEventListener("visibilitychange", wakeWhenVisible);

    async function poll() {
      while (!cancelled && mountedRef.current) {
        if (!isPageVisible()) {
          await waitForNextPoll(CHROME_STATUS_HIDDEN_CHECK_MS);
          continue;
        }
        try {
          const data = await getChromeStatus(client.id);
          if (cancelled || !mountedRef.current) break;

          const pendingChromeAction = String(data?.pending_chrome_action ?? "none").toLowerCase();
          hotPollObservationRef.current = {
            receivedAt: Date.now(),
            pendingChromeAction: pendingChromeAction || "none",
            pendingReboot: data?.pending_reboot === true,
            pendingShutdown: data?.pending_shutdown === true,
            state: data?.state ?? null,
          };

          if (data?.presence) setLivePresence(data.presence);
          if (data?.chrome_status != null) setLiveChromeStatus(data.chrome_status);
          if (data?.chrome_color != null)  setLiveChromeColor(data.chrome_color);
          let polledChromeRunning = null;
          let polledChromeRunningHasValue = false;
          if (typeof data?.chrome_running === "boolean") {
            polledChromeRunning = data.chrome_running;
            polledChromeRunningHasValue = true;
          } else if (typeof data?.chromeRunning === "boolean") {
            polledChromeRunning = data.chromeRunning;
            polledChromeRunningHasValue = true;
          }
          if (data?.pending_chrome_action != null) {
            setLocalPendingAction(pendingChromeAction || "none");
          }
          if (data?.state) setLocalClientState(data.state);

          const nextDetailHotFields = pickDetailHotFields(data);
          if (Object.keys(nextDetailHotFields).length > 0) {
            setLiveDetailHotFields((prev) => ({ ...prev, ...nextDetailHotFields }));
          }

          const nextDisplayResolution = pickDisplayResolutionFields(data);
          if (Object.keys(nextDisplayResolution).length > 0) {
            setLiveDisplayResolution((prev) => ({ ...prev, ...nextDisplayResolution }));
          }

          const nextNetworkStatus = pickNetworkFields(data);
          if (Object.keys(nextNetworkStatus).length > 0) {
            setLiveNetworkStatus((prev) => ({ ...prev, ...nextNetworkStatus }));
          }

          const nextUpdateFields = pickUpdateFields(data);
          if (Object.keys(nextUpdateFields).length > 0) {
            setLiveUpdateFields((prev) => ({ ...prev, ...nextUpdateFields }));
          }

          if (data?.livestream_status !== undefined) setLiveLivestreamStatus(data.livestream_status ?? null);
          if (data?.livestream_process_status !== undefined) setLiveLivestreamProcessStatus(data.livestream_process_status ?? null);
          if (data?.livestream_desired_state !== undefined) setLiveLivestreamDesiredState(data.livestream_desired_state ?? "stopped");
          if (data?.livestream_stop_reason !== undefined) setLiveLivestreamStopReason(data.livestream_stop_reason ?? null);

          const { hasStepField, stepName, stepTimestamp } = resolveChromeStepPayload(data);
          if (hasStepField) {
            setLiveStep(stepName);
            liveStepRef.current          = stepName;
            liveStepTimestampRef.current = stepTimestamp;
            setLiveChromeRunning((prev) => {
              const fallback = polledChromeRunningHasValue ? polledChromeRunning : prev;
              const next = inferChromeRunningFromStep(stepName, fallback);
              liveChromeRunningRef.current = next;
              return next;
            });
          } else if (polledChromeRunningHasValue) {
            liveChromeRunningRef.current = polledChromeRunning;
            setLiveChromeRunning(polledChromeRunning);
          }

          if (typeof data?.browser_requested === "boolean") {
            setLiveBrowserRequested(data.browser_requested);
          }

          if (data?.uptime != null) {
            const parsed = parseInt(String(data.uptime), 10);
            if (!isNaN(parsed) && parsed >= 0) {
              uptimeBaseRef.current  = parsed;
              uptimeFetchRef.current = Date.now();
              setUptime(parsed);
            }
          }

          nextPollMs =
            chromeStatusNeedsFastPolling(data) || Date.now() < hotPollFastUntilRef.current
              ? CHROME_STATUS_ACTIVE_POLL_MS
              : CHROME_STATUS_IDLE_POLL_MS;
        } catch {
          // Presence is canonical server state. If the hot poll cannot obtain a
          // fresh server evaluation, fail closed locally instead of keeping a
          // stale online value. Retry at the historical active cadence.
          if (!cancelled && mountedRef.current) {
            setLivePresence((previous) => presenceFetchFailed(previous));
          }
          nextPollMs = CHROME_STATUS_ACTIVE_POLL_MS;
        }
        await waitForNextPoll(nextPollMs);
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (typeof hotPollWakeRef.current === "function") hotPollWakeRef.current();
      hotPollWakeRef.current = null;
      window.removeEventListener("focus", wakeWhenVisible);
      document.removeEventListener("visibilitychange", wakeWhenVisible);
    };
  }, [client?.id]);

  // ---------------------------------------------------------------------------
  // Cleanup ved unmount
  // ---------------------------------------------------------------------------
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (localOsUpdateBusyTimerRef.current) {
        window.clearTimeout(localOsUpdateBusyTimerRef.current);
      }
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Action-pending polling
  // ---------------------------------------------------------------------------
  const [clientActionPending, setClientActionPending] = useState(false);
  const actionPollStopRef = useRef(false);

  const cancelActionPoll = useCallback(() => {
    actionPollStopRef.current = true;
    hotPollFastUntilRef.current = 0;
    setClientActionPending(false);
    setLocalPendingAction("none");
  }, []);

  useEffect(() => {
    if (onCancelActionPollRef) {
      onCancelActionPollRef.current = cancelActionPoll;
    }
  }, [onCancelActionPollRef, cancelActionPoll]);

  const startActionConfirmationPolling = useCallback((action) => {
    actionPollStopRef.current = false;
    setClientActionPending(true);
    hotPollFastUntilRef.current = Date.now() + ACTION_POLL_MAX_MS;
    if (typeof hotPollWakeRef.current === "function") hotPollWakeRef.current();

    const startTime    = Date.now();
    const startTimeISO = new Date(startTime).toISOString();
    const normalizedAction = action === "restart" ? "reboot" : action;
    const systemPowerAction = normalizedAction === "reboot" || normalizedAction === "shutdown";

    // Display actions retain step-based confirmation. Reboot/shutdown are
    // canonical System commands and are confirmed from their dedicated
    // response-only projections, never pending_chrome_action.
    const terminalSteps = TERMINAL_STEPS_BY_ACTION[action] ?? DEFAULT_TERMINAL_STEPS;

    async function pollForConfirmation() {
      while (!actionPollStopRef.current && mountedRef.current) {
        if (Date.now() - startTime > ACTION_POLL_MAX_MS) break;

        await new Promise((res) => setTimeout(res, ACTION_POLL_MS));
        if (actionPollStopRef.current || !mountedRef.current) break;

        const observation = hotPollObservationRef.current;
        // En observation fra før action-requesten må aldrig frigive låsen.
        // Hot poll'en er den eneste DB-backed observation under actionen.
        if (!observation || observation.receivedAt < startTime) continue;

        if (observation.state) setLocalClientState(observation.state);

        let actionClear = false;
        if (systemPowerAction) {
          const pending = normalizedAction === "shutdown"
            ? observation.pendingShutdown === true
            : observation.pendingReboot === true;
          setLocalPendingAction("none");
          actionClear = !pending;
        } else {
          const pca = String(observation.pendingChromeAction ?? "none").toLowerCase();
          setLocalPendingAction(pca || "none");
          actionClear = !pca || pca === "none";
        }

        if (!actionClear) continue;

        const elapsed = Date.now() - startTime;
        if (elapsed < ACTION_MIN_LOCK_MS) continue;

        if (systemPowerAction) {
          // Backend holder pending_reboot=true efter systemctl-success indtil
          // canonical Status boot_id beviser en ny boot. Shutdown bliver
          // terminal når System command completion er registreret.
          break;
        }

        const stepTimestamp = liveStepTimestampRef.current;
        const stepIsStale   = !stepTimestamp || stepTimestamp < startTimeISO;

        const currentStep = stepIsStale
          ? ""
          : String(liveStepRef.current ?? "").toLowerCase();

        if (terminalSteps.has(currentStep)) break;
        if (BUSY_CHROME_STEPS.has(currentStep)) continue;
        if (elapsed < ACTION_NULL_STEP_MS) continue;
        break;
      }

      hotPollFastUntilRef.current = 0;
      if (mountedRef.current && !actionPollStopRef.current) {
        try {
          const refresh = silentRefresh ?? handleRefresh;
          await refresh();
        } catch {
          // Ignorer
        }
        setClientActionPending(false);
      }
    }

    pollForConfirmation();
  }, [silentRefresh, handleRefresh]);

  // ---------------------------------------------------------------------------
  // Handlinger
  // ---------------------------------------------------------------------------
  const handleClientAction = useCallback(
    async (action) => {
      if (!client?.id) return;
      await clientAction(client.id, action);
      const normalizedAction = action === "restart" ? "reboot" : action;
      if (normalizedAction === "reboot" || normalizedAction === "shutdown") {
        setLocalPendingAction("none");
        setLocalClientState(normalizedAction === "shutdown" ? "shutdown" : "rebooting");
      } else {
        setLocalPendingAction(action);
      }
      startActionConfirmationPolling(action);
    },
    [client?.id, startActionConfirmationPolling]
  );

  const handleOpenTerminal = useCallback(() => {
    if (!client?.id) return;
    window.open(`/terminal/${client.id}`, "_blank", "noopener");
  }, [client?.id]);

  const handleOpenRemoteDesktop = useCallback(() => {
    if (client?.id) openRemoteDesktop(client.id);
  }, [client?.id]);

  const refreshAfterExternalCommand = useCallback(
    async ({ pendingChromeAction, clientState } = {}) => {
      if (pendingChromeAction !== undefined) {
        const pca = String(pendingChromeAction || "none").toLowerCase();
        setLocalPendingAction(pca || "none");
      }
      if (clientState) setLocalClientState(clientState);

      try {
        if (typeof silentRefresh === "function") {
          await silentRefresh();
        } else if (typeof handleRefresh === "function") {
          await handleRefresh();
        }
      } catch {
        // Ignorer refresh-fejl efter eksterne kommandoer.
      }
    },
    [silentRefresh, handleRefresh]
  );

  const refreshAfterUbuntuUpdate = useCallback(
    async ({ optimistic = false } = {}) => {
      if (optimistic) {
        setLocalOsUpdateBusy(true);
        if (localOsUpdateBusyTimerRef.current) {
          window.clearTimeout(localOsUpdateBusyTimerRef.current);
        }
        localOsUpdateBusyTimerRef.current = window.setTimeout(() => {
          setLocalOsUpdateBusy(false);
          localOsUpdateBusyTimerRef.current = null;
        }, 15_000);
      }

      try {
        if (typeof silentRefresh === "function") {
          await silentRefresh();
        } else if (typeof handleRefresh === "function") {
          await handleRefresh();
        }
      } catch {
        // Ignorer refresh-fejl efter Ubuntu-opdatering.
      }
    },
    [silentRefresh, handleRefresh]
  );

  const refreshAfterConfigSaved = useCallback(
    async () => {
      try {
        if (typeof silentRefreshAll === "function") {
          await silentRefreshAll();
        } else if (typeof silentRefresh === "function") {
          await silentRefresh();
        } else if (typeof handleRefresh === "function") {
          await handleRefresh();
        }
      } catch {
        // Ignorer refresh-fejl efter konfigurationsændring.
      }
    },
    [silentRefreshAll, silentRefresh, handleRefresh]
  );

  // ---------------------------------------------------------------------------
  // Afledte værdier
  // ---------------------------------------------------------------------------
  const clientOnline = livePresence?.is_online === true;
  const lastSeen = livePresence?.status?.reported_at ?? null;
  const displayUptime = uptime != null ? uptime : client?.uptime ?? null;

  // Livestream auto-heal efter hurtig reboot:
  // Presence-leasen kan være længere end selve rebootet, så clientOnline
  // når ikke altid at blive false. Uptime-reset er derfor det
  // mest pålidelige signal for "ny boot" mens detaljesiden står åben.
  const lastLivestreamBootUptimeRef = useRef(null);
  const lastLivestreamBootRefreshAtRef = useRef(0);

  useEffect(() => {
    const current = Number.parseInt(String(displayUptime ?? ""), 10);
    if (!Number.isFinite(current) || current < 0) return;

    const previous = lastLivestreamBootUptimeRef.current;
    lastLivestreamBootUptimeRef.current = current;

    if (previous === null || previous === undefined) return;

    const uptimeDroppedAfterReboot = previous > 120 && current + 30 < previous;
    const cooldownOk = Date.now() - lastLivestreamBootRefreshAtRef.current > 30_000;

    if (uptimeDroppedAfterReboot && cooldownOk) {
      lastLivestreamBootRefreshAtRef.current = Date.now();
      if (typeof onRestartStream === "function") {
        try { onRestartStream(); } catch {}
      }
    }
  }, [displayUptime, onRestartStream]);

  const effectivePendingAction = localOsUpdateBusy
    ? "os_update"
    : localPendingAction ?? client?.pending_chrome_action ?? "none";

  const effectiveClientState = localOsUpdateBusy
    ? "updating"
    : localClientState ?? client?.state ?? "normal";

  const wakeCompleteWithoutPending =
    ["display_wake_complete", "system_wake_complete"].includes(String(liveStep || "").trim().toLowerCase()) &&
    String(effectivePendingAction || "none").trim().toLowerCase() === "none";

  const liveClient = useMemo(
    () => ({
      ...(client || {}),
      ...liveDetailHotFields,
      ...liveDisplayResolution,
      ...liveNetworkStatus,
      ...liveUpdateFields,
      pending_reboot: liveUpdateFields.pending_reboot ?? client?.pending_reboot ?? false,
      pending_shutdown: liveUpdateFields.pending_shutdown ?? client?.pending_shutdown ?? false,
      pending_os_update: localOsUpdateBusy ? true : (liveUpdateFields.pending_os_update ?? client?.pending_os_update ?? false),
      livestream_status: liveLivestreamStatus ?? client?.livestream_status ?? null,
      livestream_process_status: liveLivestreamProcessStatus ?? client?.livestream_process_status ?? null,
      livestream_desired_state: liveLivestreamDesiredState || "stopped",
      // null er en autoritativ værdi her: den betyder at mailbox/reason er ryddet.
      // Brug derfor ikke ??-fallback til et ældre client-snapshot.
      livestream_stop_reason: liveLivestreamStopReason,
      presence: livePresence,
      uptime: displayUptime ?? client?.uptime ?? null,
      pending_chrome_action: effectivePendingAction,
      state: effectiveClientState,
      chrome_status: liveChromeStatus ?? client?.chrome_status ?? null,
      chrome_color: liveChromeColor ?? client?.chrome_color ?? null,
      chrome_step: liveStep ?? client?.chrome_step ?? null,
      last_chrome_step: liveStep ?? client?.last_chrome_step ?? client?.chrome_step ?? null,
      chrome_running: liveChromeRunning,
      browser_requested: liveBrowserRequested,
    }),
    [
      client,
      liveDetailHotFields,
      liveDisplayResolution,
      liveNetworkStatus,
      liveUpdateFields,
      localOsUpdateBusy,
      displayUptime,
      livePresence,
      effectivePendingAction,
      effectiveClientState,
      liveChromeStatus,
      liveChromeColor,
      liveStep,
      liveChromeRunning,
      liveBrowserRequested,
      liveLivestreamStatus,
      liveLivestreamProcessStatus,
      liveLivestreamDesiredState,
      liveLivestreamStopReason,
    ]
  );

  const networkUnavailable = isNetworkUnavailable(liveClient);
  const networkMessage = getNetworkStatusMessage(liveClient);

  const handleControlRoomBack = useCallback(() => {
    // Navigation er ikke en eksplicit stophandling. Livestreamens desired state
    // ejes af start/stop-knapperne og må ikke ændres, når Control Room forlades.
    navigate(-1);
  }, [navigate]);

  return (
    <Box
      sx={{
        minHeight: "100vh",
        bgcolor: "transparent",
        color: "#f8fafc",
        py: isMobile ? 1 : 2.5,
      }}
    >
      <Container
        maxWidth="xl"
        disableGutters
        sx={{
          px: isMobile ? 1 : 3,
        }}
      >
        <Box sx={{ display: "flex", flexDirection: "column", gap: isMobile ? 1.25 : 2 }}>
          <ControlRoomTopbar
            client={liveClient}
            clientOnline={clientOnline}
            networkUnavailable={networkUnavailable}
            networkMessage={networkMessage}
            liveChromeStatus={liveChromeStatus}
            clientState={effectiveClientState}
            refreshing={refreshing}
            onRefresh={handleRefresh}
            onBack={handleControlRoomBack}
            isMobile={isMobile}
          />

          <Box
            sx={{
              ...glassPanelSx(theme, isMobile),
              p: isMobile ? 1.5 : 2.25,
            }}
          >
            <Suspense fallback={<SectionLoadingFallback label="Indlæser klienthandlinger…" />}>
              <ClientDetailsActionsSection
              clientId={client?.id}
              clientState={effectiveClientState}
              displayPower={liveClient?.display_power ?? client?.display_power ?? null}
              pendingChromeAction={effectivePendingAction}
              handleClientAction={handleClientAction}
              handleOpenTerminal={handleOpenTerminal}
              handleOpenRemoteDesktop={handleOpenRemoteDesktop}
              refreshing={refreshing}
              clientOnline={clientOnline}
              clientActionPending={wakeCompleteWithoutPending ? false : clientActionPending}
              liveStep={liveStep}
              liveChromeStatus={liveChromeStatus}
              chromeRunning={liveChromeRunning}
              browserRequested={liveBrowserRequested}
              clientStatus={client?.status}
              pendingOsUpdate={liveClient?.pending_os_update}
              serviceUbuntuUpdateStatus={liveClient?.service_ubuntu_update_status}
              ubuntuUpdatesAvailable={liveClient?.ubuntu_updates_available}
              ubuntuUpdateStatus={liveClient?.ubuntu_update_status}
              ubuntuUpdateStep={liveClient?.ubuntu_update_step}
              ubuntuUpdateMessage={liveClient?.ubuntu_update_message}
              ubuntuUpdateError={liveClient?.ubuntu_update_error}
              ubuntuUpdateStartedAt={liveClient?.ubuntu_update_started_at}
              ubuntuUpdateUpdatedAt={liveClient?.ubuntu_update_updated_at}
              ubuntuUpdateFinishedAt={liveClient?.ubuntu_update_finished_at}
              ubuntuUpdateProgress={liveClient?.ubuntu_update_progress}
              ubuntuUpdatePackageCount={liveClient?.ubuntu_update_package_count}
              ubuntuUpdateRebootRequired={liveClient?.ubuntu_update_reboot_required}
              livestreamStatus={liveClient?.livestream_status}
              livestreamProcessStatus={liveClient?.livestream_process_status}
              clientflowDeployment={clientflowDeployment}
              showSnackbar={showSnackbar}
              compact
              controlRoom
              hideHeader
              />
            </Suspense>
          </Box>

          <Box sx={{ ...glassPanelSx(theme, isMobile), p: isMobile ? 1.25 : 1.75 }}>
            <Box
              sx={{
                borderRadius: isMobile ? 2.5 : 3.5,
                overflow: "visible",
                border: "1px solid rgba(148,163,184,0.16)",
                bgcolor: "rgba(2,6,23,0.42)",
                "& > .MuiBox-root > .MuiCard-root, & > .MuiCard-root": {
                  mb: 0,
                  borderRadius: isMobile ? 2.25 : 3,
                  boxShadow: "none",
                  background: "linear-gradient(180deg, rgba(2,6,23,0.58), rgba(15,23,42,0.42))",
                  color: "#e5eefb",
                },
              }}
            >
              <Suspense fallback={<SectionLoadingFallback label="Indlæser livestream…" />}>
                <ClientDetailsLivestreamSection
                client={liveClient}
                clientId={client?.id}
                streamKey={streamKey}
                refreshing={refreshing}
                onRestartStream={onRestartStream}
                onCommandSent={refreshAfterExternalCommand}
                onDisplayResolutionSettingsSaved={silentRefresh}
                clientOnline={clientOnline}
                />
              </Suspense>
            </Box>
          </Box>


          <Box sx={{ ...glassPanelSx(theme, isMobile), p: isMobile ? 1.5 : 2.25 }}>
            <Suspense fallback={<SectionLoadingFallback label="Indlæser klientoplysninger…" />}>
              <ClientDetailsInfoSection
              client={liveClient}
              markedDays={markedDays}
              uptime={displayUptime}
              lastSeen={lastSeen}
              setCalendarDialogOpen={setCalendarDialogOpen}
              clientOnline={clientOnline}
              calendarLoading={calendarLoading}
              showSnackbar={showSnackbar}
              onUbuntuUpdateStarted={refreshAfterUbuntuUpdate}
              onDiagnosticsRefresh={silentRefresh}
              onConfigSaved={refreshAfterConfigSaved}
              handleClientAction={handleClientAction}
              clientflowDeployment={clientflowDeployment}
              onClientflowDeploymentChange={setClientflowDeployment}
              />
            </Suspense>
          </Box>

        </Box>

        {calendarDialogOpen && (
          <Suspense fallback={null}>
            <ClientCalendarDialog
              open
              onClose={() => setCalendarDialogOpen(false)}
              clientId={client?.id}
            />
          </Suspense>
        )}


        <AppSnackbar
          open={snackbar.open}
          message={snackbar.message}
          severity={snackbar.severity}
          onClose={handleCloseSnackbar}
        />
      </Container>
    </Box>
  );
}
