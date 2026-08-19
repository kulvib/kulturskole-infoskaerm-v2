import React, { useEffect, useRef, useState, useMemo, useCallback } from "react";
import {
  Box, Card, Typography, CircularProgress, Alert, IconButton,
  Tooltip, Grid, Stack, Divider, useMediaQuery, Button, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, MenuItem
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import FullscreenIcon from "@mui/icons-material/Fullscreen";
import { useTheme, alpha } from "@mui/material/styles";
import { useAuth } from "../../auth/AuthProvider";
import { apiUrl, authHeaders, updateClient } from "../../api";

const HEALTH_POLL_MS = 1000;
const LAST_SEGMENT_POLL_MS = 1000;
const AUTO_RECONNECT_DELAY_MS = 2000;
const STALE_SEGMENT_RESTART_AFTER_SECONDS = 90;
const STALE_SEGMENT_RESTART_COOLDOWN_MS = 90_000;
const STALE_WATCHDOG_POLL_MS = 5_000;
const VIEWER_HEARTBEAT_MS = 10_000;
const FULLSCREEN_WATCHDOG_MS = 2_000;
const HIDDEN_INACTIVITY_STOP_MS = 3 * 60 * 1000;
const INACTIVITY_STOP_MESSAGE = "Siden har ikke været besøgt i 3 min., derfor er livestreamen stoppet.";

// Low-latency regular HLS target. Med 2s segmenter starter vi efter 2 manifest-segmenter
// og holder browseren tættere på live edge uden at bruge 1-segment-start.
const HLS_INITIAL_MANIFEST_SEGMENTS = 2;
const HLS_LIVE_SYNC_SECONDS = 4;
const HLS_MAX_LATENCY_SECONDS = 14;
const HLS_CATCH_UP_SEEK_SECONDS = 10;


const DISPLAY_AUTO_OPTION = {
  value: "auto",
  label: "Auto-detekter skærmstørrelse",
  mode: "auto",
  width: null,
  height: null,
  refreshRate: null,
  source: "auto",
};

const DISPLAY_CUSTOM_OPTION = {
  value: "custom",
  label: "Brugerdefineret bredde/højde",
  mode: "fixed",
  width: null,
  height: null,
  refreshRate: null,
  source: "custom",
};

// Fallback bruges kun hvis klienten endnu ikke har rapporteret en mode-liste.
// Normalvis bygges listen fra client.display_detected_outputs.
const FALLBACK_DISPLAY_RESOLUTION_OPTIONS = [
  { value: "fallback_full_hd", label: "Full HD · 1920×1080", mode: "fixed", width: 1920, height: 1080, refreshRate: null, source: "fallback" },
  { value: "fallback_ultrawide_qhd", label: "Ultrawide QHD · 3440×1440", mode: "fixed", width: 3440, height: 1440, refreshRate: null, source: "fallback" },
  DISPLAY_CUSTOM_OPTION,
];

function parseDetectedOutputs(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;

  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
      if (Array.isArray(parsed?.outputs)) return parsed.outputs;
      if (Array.isArray(parsed?.monitors)) return parsed.monitors;
      return [];
    } catch {
      return [];
    }
  }

  if (Array.isArray(raw?.outputs)) return raw.outputs;
  if (Array.isArray(raw?.monitors)) return raw.monitors;
  return [];
}

function parseModeString(value) {
  const s = String(value || "").trim();
  const m = s.match(/(\d{3,5})\s*x\s*(\d{3,5})(?:\s*[@/]\s*([0-9]+(?:\.[0-9]+)?))?/i);
  if (!m) return null;
  return {
    width: Number(m[1]),
    height: Number(m[2]),
    refreshRate: m[3] ? Number(m[3]) : null,
  };
}

function normalizeDetectedMode(mode, outputName = "") {
  if (!mode) return null;

  if (typeof mode === "string") {
    const parsed = parseModeString(mode);
    if (!parsed) return null;
    return {
      output: outputName,
      width: parsed.width,
      height: parsed.height,
      refreshRate: parsed.refreshRate,
      current: false,
      preferred: false,
    };
  }

  const width = parseOptionalNumber(
    mode.width ?? mode.w ?? mode.mode_width ?? mode.current_width ?? mode.resolution_width
  );
  const height = parseOptionalNumber(
    mode.height ?? mode.h ?? mode.mode_height ?? mode.current_height ?? mode.resolution_height
  );

  if (!width || !height) {
    const parsed = parseModeString(mode.name || mode.label || mode.resolution || mode.mode || "");
    if (!parsed) return null;
    return {
      output: outputName,
      width: parsed.width,
      height: parsed.height,
      refreshRate: parsed.refreshRate,
      current: !!mode.current || !!mode.active,
      preferred: !!mode.preferred,
    };
  }

  return {
    output: String(mode.output || mode.name || mode.connector || outputName || "").trim(),
    width,
    height,
    refreshRate: parseOptionalNumber(
      mode.refreshRate ?? mode.refresh_rate ?? mode.rate ?? mode.current_refresh_rate ?? mode.refresh
    ),
    current: !!mode.current || !!mode.active || !!mode.selected,
    preferred: !!mode.preferred || !!mode.recommended,
  };
}

function makeClientModeOption(mode, index = 0) {
  const width = parseOptionalNumber(mode?.width);
  const height = parseOptionalNumber(mode?.height);
  if (!width || !height) return null;

  const refreshRate = parseOptionalNumber(mode?.refreshRate);
  const output = String(mode?.output || "").trim();
  const activeText = mode?.current ? " · aktiv" : mode?.preferred ? " · anbefalet" : "";
  const refreshText = refreshRate ? ` @ ${Number(refreshRate).toFixed(2).replace(/\.00$/, "")}Hz` : "";
  const outputText = output ? `${output} · ` : "";
  const value = [
    "client",
    output || "output",
    Math.round(width),
    Math.round(height),
    refreshRate ? Number(refreshRate).toFixed(2) : "default",
    index,
  ].join(":");

  return {
    value,
    label: `${outputText}${Math.round(width)}×${Math.round(height)}${refreshText}${activeText}`,
    mode: "fixed",
    width,
    height,
    refreshRate,
    output,
    source: "client",
    current: !!mode?.current,
    preferred: !!mode?.preferred,
  };
}

function getClientDisplayResolutionOptions(client) {
  const outputs = parseDetectedOutputs(client?.display_detected_outputs);
  const currentOutput = String(client?.display_resolution_current_output || "").trim();
  const currentWidth = parseOptionalNumber(client?.display_resolution_current_width);
  const currentHeight = parseOptionalNumber(client?.display_resolution_current_height);
  const currentRefreshRate = parseOptionalNumber(client?.display_resolution_current_refresh_rate);

  const modes = [];

  outputs.forEach((output) => {
    if (!output || typeof output !== "object") return;
    const outputName = String(
      output.name || output.output || output.connector || output.id || output.display || currentOutput || ""
    ).trim();

    const outputModes =
      output.modes ||
      output.available_modes ||
      output.resolutions ||
      output.supported_modes ||
      output.mode_list ||
      [];

    if (Array.isArray(outputModes)) {
      outputModes.forEach((mode) => {
        const normalized = normalizeDetectedMode(mode, outputName);
        if (normalized) modes.push(normalized);
      });
    }

    const activeMode = normalizeDetectedMode({
      output: outputName,
      width: output.current_width ?? output.width,
      height: output.current_height ?? output.height,
      refreshRate: output.current_refresh_rate ?? output.refresh_rate ?? output.refreshRate,
      current: true,
    }, outputName);
    if (activeMode) modes.push(activeMode);
  });

  if (currentWidth && currentHeight) {
    modes.unshift({
      output: currentOutput,
      width: currentWidth,
      height: currentHeight,
      refreshRate: currentRefreshRate,
      current: true,
      preferred: false,
    });
  }

  const seen = new Set();
  const options = [];
  modes.forEach((mode) => {
    const width = parseOptionalNumber(mode.width);
    const height = parseOptionalNumber(mode.height);
    if (!width || !height) return;

    const refreshRate = parseOptionalNumber(mode.refreshRate);
    const output = String(mode.output || currentOutput || "").trim();
    const key = [output, Math.round(width), Math.round(height), refreshRate ? Number(refreshRate).toFixed(2) : ""].join("|");
    if (seen.has(key)) return;
    seen.add(key);

    const option = makeClientModeOption({ ...mode, output, width, height, refreshRate }, options.length);
    if (option) options.push(option);
  });

  options.sort((a, b) => {
    if (a.current !== b.current) return a.current ? -1 : 1;
    const outputCompare = String(a.output || "").localeCompare(String(b.output || ""), "da-DK");
    if (outputCompare !== 0) return outputCompare;
    const pixelCompare = (b.width * b.height) - (a.width * a.height);
    if (pixelCompare !== 0) return pixelCompare;
    return (b.refreshRate || 0) - (a.refreshRate || 0);
  });

  if (options.length === 0) {
    return FALLBACK_DISPLAY_RESOLUTION_OPTIONS;
  }

  return [...options, DISPLAY_CUSTOM_OPTION];
}

function findDisplayResolutionOption(value, options = []) {
  const all = [...(options || []), DISPLAY_AUTO_OPTION, DISPLAY_CUSTOM_OPTION, ...FALLBACK_DISPLAY_RESOLUTION_OPTIONS];
  return all.find((p) => p.value === value) || DISPLAY_CUSTOM_OPTION;
}

function findOptionByDimensions(width, height, refreshRate = null, options = []) {
  const w = parseOptionalNumber(width);
  const h = parseOptionalNumber(height);
  const r = parseOptionalNumber(refreshRate);
  if (!w || !h) return null;

  const exactRefresh = (options || []).find((p) =>
    p.value !== "auto" &&
    p.value !== "custom" &&
    p.width === w &&
    p.height === h &&
    r !== null &&
    p.refreshRate !== null &&
    sameOptionalNumber(p.refreshRate, r)
  );
  if (exactRefresh) return exactRefresh;

  return (options || []).find((p) =>
    p.value !== "auto" &&
    p.value !== "custom" &&
    p.width === w &&
    p.height === h
  ) || null;
}

function getDisplayResolutionPreset(value) {
  // Kompatibilitets-wrapper til ældre kald. I den nye dialog bruges
  // findDisplayResolutionOption(value, displayResolutionOptions).
  return findDisplayResolutionOption(value, FALLBACK_DISPLAY_RESOLUTION_OPTIONS);
}

function findPresetByDimensions(width, height) {
  return findOptionByDimensions(width, height, null, FALLBACK_DISPLAY_RESOLUTION_OPTIONS);
}

function getInitialDisplaySettingsForm(client, options = null) {
  const displayOptions = options || getClientDisplayResolutionOptions(client);
  const configuredMode = String(client?.display_resolution_mode || "auto").toLowerCase();
  const configuredWidth = client?.display_resolution_width;
  const configuredHeight = client?.display_resolution_height;
  const configuredRefreshRate = client?.display_resolution_refresh_rate;

  if (configuredMode === "fixed" && configuredWidth && configuredHeight) {
    const configuredOption = findOptionByDimensions(configuredWidth, configuredHeight, configuredRefreshRate, displayOptions);
    return {
      preset: configuredOption?.value || "custom",
      width: String(configuredWidth || ""),
      height: String(configuredHeight || ""),
      refreshRate: String(configuredRefreshRate ?? ""),
    };
  }

  const currentWidth = client?.display_resolution_current_width;
  const currentHeight = client?.display_resolution_current_height;
  const currentRefreshRate = client?.display_resolution_current_refresh_rate;
  const currentOption = findOptionByDimensions(currentWidth, currentHeight, currentRefreshRate, displayOptions);

  if (currentOption) {
    return {
      preset: currentOption.value,
      width: String(currentOption.width || ""),
      height: String(currentOption.height || ""),
      refreshRate: String(currentOption.refreshRate ?? currentRefreshRate ?? ""),
    };
  }

  if (currentWidth && currentHeight) {
    return {
      preset: "custom",
      width: String(currentWidth),
      height: String(currentHeight),
      refreshRate: String(currentRefreshRate ?? ""),
    };
  }

  const firstClientOption = displayOptions.find((p) => p.value !== "custom" && p.value !== "auto") || DISPLAY_CUSTOM_OPTION;
  return {
    preset: firstClientOption.value,
    width: String(firstClientOption.width || ""),
    height: String(firstClientOption.height || ""),
    refreshRate: String(firstClientOption.refreshRate ?? ""),
  };
}

function normalizeDisplayResolutionStatus(status) {
  return String(status || "unknown").trim().toLowerCase();
}

function formatCurrentDisplayResolution(client) {
  if (client?.display_resolution_current_width && client?.display_resolution_current_height) {
    return `${client.display_resolution_current_width}×${client.display_resolution_current_height}${
      client?.display_resolution_current_refresh_rate
        ? ` @ ${client.display_resolution_current_refresh_rate}Hz`
        : ""
    }${client?.display_resolution_current_output ? ` · ${client.display_resolution_current_output}` : ""}`;
  }
  return "Ikke rapporteret endnu";
}

function getDisplayRuntimeSignature(client) {
  const output = String(client?.display_resolution_current_output || "").trim();
  const width = parseOptionalNumber(client?.display_resolution_current_width);
  const height = parseOptionalNumber(client?.display_resolution_current_height);
  const refresh = parseOptionalNumber(client?.display_resolution_current_refresh_rate);

  if (!output && !width && !height) return "";

  return [
    output || "unknown-output",
    width ?? "unknown-width",
    height ?? "unknown-height",
    refresh !== null ? Number(refresh).toFixed(2) : "unknown-refresh",
  ].join("|");
}

function parseOptionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function sameOptionalNumber(a, b, tolerance = 0.01) {
  const na = parseOptionalNumber(a);
  const nb = parseOptionalNumber(b);
  if (na === null && nb === null) return true;
  if (na === null || nb === null) return false;
  return Math.abs(na - nb) <= tolerance;
}

function formatResolutionLabel(width, height, refreshRate = null) {
  const w = parseOptionalNumber(width);
  const h = parseOptionalNumber(height);
  if (!w || !h) return "Ukendt opløsning";
  const refresh = parseOptionalNumber(refreshRate);
  return `${w}×${h}${refresh ? ` @ ${refresh}Hz` : ""}`;
}

function getLivestreamDisplaySize(client) {
  const currentWidth = parseOptionalNumber(client?.display_resolution_current_width);
  const currentHeight = parseOptionalNumber(client?.display_resolution_current_height);
  if (currentWidth && currentHeight) {
    return { width: currentWidth, height: currentHeight, source: "current" };
  }

  const configuredWidth = parseOptionalNumber(client?.display_resolution_width);
  const configuredHeight = parseOptionalNumber(client?.display_resolution_height);
  if (configuredWidth && configuredHeight) {
    return { width: configuredWidth, height: configuredHeight, source: "configured" };
  }

  return { width: 1920, height: 1080, source: "fallback" };
}

function getLivestreamAspectRatio(client) {
  const { width, height } = getLivestreamDisplaySize(client);
  if (!width || !height) return "16 / 9";
  return `${width} / ${height}`;
}


function getDisplayResolutionStatusMeta(status, presetValue = "auto", error = "", actionValue = null) {
  const s = normalizeDisplayResolutionStatus(status);
  const action = String(actionValue || "").trim().toLowerCase();
  const isDetect = action === "detect";
  const isAuto = presetValue === "auto";

  if (s === "pending") {
    return {
      busy: true,
      severity: "info",
      title: isDetect || isAuto
        ? "Auto-detektering er startet"
        : "Skærmændring er sendt til klienten",
      detail: isDetect || isAuto
        ? "Afventer at klienten rapporterer den aktuelle skærm."
        : "Afventer at klienten henter den nye konfiguration og rapporterer tilbage.",
      short: isDetect || isAuto ? "Auto-detektering kører" : "Skærmændring afventer klienten",
    };
  }

  if (s === "applying") {
    return {
      busy: true,
      severity: "info",
      title: "Klienten anvender skærmopløsningen",
      detail: "Klienten kører xrandr og tester den valgte opløsning.",
      short: "Klienten anvender opløsningen…",
    };
  }

  if (s === "detected") {
    return {
      busy: false,
      severity: "success",
      title: "Auto-detektering gennemført",
      detail: "Klienten har rapporteret den aktuelle skærmopløsning.",
      short: "Auto-detektering gennemført",
    };
  }

  if (s === "applied") {
    return {
      busy: false,
      severity: "success",
      title: "Skærmopløsning anvendt",
      detail: "Klienten har anvendt opløsningen og rapporteret den tilbage.",
      short: "Skærmopløsning anvendt",
    };
  }

  if (s === "error") {
    return {
      busy: false,
      severity: "error",
      title: "Skærmændring fejlede",
      detail: error || "Klienten rapporterede en fejl under skærmhåndteringen.",
      short: "Skærmændring fejlede",
    };
  }

  return {
    busy: false,
    severity: "info",
    title: "Ingen aktiv skærmproces",
    detail: "Der er ikke en aktiv auto-detektering eller skærmændring i gang.",
    short: "Ingen aktiv skærmproces",
  };
}

function getOptimisticDisplayResolutionMeta(action, isSaveOnly = false) {
  const a = String(action || "").trim().toLowerCase();

  if (a === "detect") {
    return {
      busy: true,
      severity: "info",
      title: "Auto-detektering er sendt til klienten",
      detail: "Venter på at klienten rapporterer den aktuelle skærm.",
      short: "Auto-detektering afventer klienten",
    };
  }

  if (a === "apply") {
    return {
      busy: true,
      severity: "info",
      title: isSaveOnly ? "Fast opløsning gemmes" : "Skærmændring er sendt til klienten",
      detail: isSaveOnly
        ? "Venter på at klienten bekræfter den faste opløsning."
        : "Venter på at klienten anvender den valgte opløsning.",
      short: isSaveOnly ? "Fast opløsning gemmes" : "Skærmændring afventer klienten",
    };
  }

  return null;
}

function getAuthHeaders(extra = {}) {
  return authHeaders(extra);
}

async function fetchWithRetry(url, options = {}, maxAttempts = 5) {
  let lastError;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const resp = await fetch(url, {
        credentials: "include",
        ...options,
        headers: { ...getAuthHeaders(), ...(options.headers || {}) },
        signal: AbortSignal.timeout(5000)
      });
      if (resp.ok || attempt === maxAttempts) return resp;
      lastError = new Error(`HTTP ${resp.status}`);
    } catch (err) {
      lastError = err;
      if (attempt < maxAttempts) {
        const delay = Math.min(500 * Math.pow(2, attempt - 1), 8000);
        await new Promise(res => setTimeout(res, delay));
      }
    }
  }
  throw lastError || new Error("All retry attempts failed");
}

async function sendLivestreamCommand(clientId, action, options = {}) {
  if (!clientId) throw new Error("Mangler klient-id");

  const { keepalive = false, timeoutMs = 8000, source = "client_details_auto" } = options || {};
  const requestOptions = {
    method: "POST",
    credentials: "include",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify({ action, source }),
  };

  if (keepalive) {
    requestOptions.keepalive = true;
  } else {
    requestOptions.signal = AbortSignal.timeout(timeoutMs);
  }

  const resp = await fetch(
    `${apiUrl}/api/livestream-v2/clients/${encodeURIComponent(clientId)}/command`,
    requestOptions
  );

  let data = null;
  try {
    data = await resp.json();
  } catch {
    // ignore empty/non-json response
  }

  if (!resp.ok) {
    const message = data?.detail || data?.message || `Kunne ikke sende ${action} (${resp.status})`;
    const lowerMessage = String(message || "").toLowerCase();

    // Backend kan returnere 400/409 hvis livestream_start allerede er lagt i kø
    // eller hvis frontend/backend midlertidigt er ude af version-sync.
    // For UI'et er det ikke en fejl: klienten har allerede en startordre.
    if (
      action === "livestream_start" &&
      (resp.status === 400 || resp.status === 409) &&
      (lowerMessage.includes("already requested") || lowerMessage.includes("allerede") || lowerMessage.includes("igang"))
    ) {
      return {
        ok: true,
        alreadyRequested: true,
        message,
      };
    }

    throw new Error(message);
  }

  return data;
}

async function sendViewerLeave(clientId, viewerId, options = {}) {
  if (!clientId || !viewerId) return null;

  const { keepalive = true, source = null } = options || {};
  const requestOptions = {
    method: "POST",
    credentials: "include",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify({
      viewer_id: viewerId,
      source: source || "client_details_livestream_leave",
    }),
  };

  if (keepalive) {
    requestOptions.keepalive = true;
  } else {
    requestOptions.signal = AbortSignal.timeout(5000);
  }

  try {
    const resp = await fetch(
      `${apiUrl}/api/livestream-v2/hls/${encodeURIComponent(clientId)}/viewer-leave`,
      requestOptions
    );
    return resp.ok ? resp.json().catch(() => ({ ok: true })) : null;
  } catch {
    // Leave-signalet er best-effort viewer-telemetri og ændrer aldrig streamens
    // permanente desired state.
    return null;
  }
}

function formatDateTimeWithDay(date) {
  if (!date) return "";
  const ukedage = ["Søndag","Mandag","Tirsdag","Onsdag","Torsdag","Fredag","Lørdag"];
  const d = new Date(date);
  const dayName = ukedage[d.getDay()];
  const day   = d.getDate().toString().padStart(2,"0");
  const month = (d.getMonth()+1).toString().padStart(2,"0");
  const year  = d.getFullYear();
  const hour  = d.getHours().toString().padStart(2,"0");
  const min   = d.getMinutes().toString().padStart(2,"0");
  const sec   = d.getSeconds().toString().padStart(2,"0");
  return `${dayName} ${day}.${month} ${year}, kl. ${hour}:${min}:${sec}`;
}

function getLagStatus(lag) {
  if (lag == null) {
    return { text: "Beregner forsinkelse …", color: "#888" };
  }

  const rounded = Math.round(lag);

  if (lag < 3) {
    return { text: "Live", color: "#43a047" };
  }

  if (lag < 20) {
    return { text: `Stream er ${rounded} sekunder forsinket`, color: "#43a047" };
  }

  if (lag < 30) {
    return { text: `Stream er ${rounded} sekunder forsinket`, color: "#f90" };
  }

  return { text: `Stream er ${rounded} sekunder forsinket`, color: "#e53935" };
}

function formatLagValue(val) {
  if (val == null) return "-";
  return Number(val).toFixed(2) + "s";
}

function extractSegNum(filename) {
  if (!filename) return null;
  const m = String(filename).match(/segment[-_](\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

export default function ClientDetailsLivestreamSection({
  client = null,
  clientId,
  refreshing: parentRefreshing = false,
  onRestartStream = null,
  onCommandSent = null,
  onDisplayResolutionSettingsSaved = null,
  streamKey = null,
  clientOnline = true
}) {
  const videoRef = useRef(null);
  const videoContainerRef = useRef(null);
  const hlsRef   = useRef(null);
  const lastHlsProgressAtRef = useRef(0);
  const lastVideoTimeRef = useRef(0);
  const viewerIdRef = useRef(`viewer-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  const viewerLeaveSentRef = useRef(false);
  const hiddenInactivityTimerRef = useRef(null);

  const [serverReady, setServerReady]           = useState(false);
  const [manifestReady, setManifestReady]       = useState(false);
  const [error, setError]                       = useState("");
  const [buffering, setBuffering]               = useState(false);
  const [currentSegNum, setCurrentSegNum]       = useState(null);
  const [fragDuration, setFragDuration]         = useState(2);
  const [lastSegNum, setLastSegNum]             = useState(null);
  const [lastSegmentLag, setLastSegmentLag]     = useState(null);
  const [lastSegmentTimestamp, setLastSegmentTimestamp] = useState(null);
  const [lastFetched, setLastFetched]           = useState(null);
  const [showControls, setShowControls]         = useState(false);
  const [localRefreshKey, setLocalRefreshKey]   = useState(0);
  const [refreshing, setRefreshing]             = useState(false);
  const [streamStale, setStreamStale]           = useState(false);
  const [autoStartStatus, setAutoStartStatus]   = useState("");
  const [autoStartError, setAutoStartError]     = useState("");
  const [healthInfo, setHealthInfo]             = useState(null);
  const [inactivityStopped, setInactivityStopped] = useState(false);
  const [inactivityStopMessage, setInactivityStopMessage] = useState("");

  const [settingsOpen, setSettingsOpen] = useState(false);
  const autoDetectOnOpenRef = useRef(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [settingsForm, setSettingsForm] = useState({
    preset: "auto",
    width: "",
    height: "",
    refreshRate: "",
  });
  const [settingsTouched, setSettingsTouched] = useState(false);
  const [displayResolutionWatching, setDisplayResolutionWatching] = useState(false);
  const [displayResolutionWatchingAction, setDisplayResolutionWatchingAction] = useState(null);
  const [displayResolutionSawWorkingState, setDisplayResolutionSawWorkingState] = useState(false);
  const [displayResolutionRequestBaseline, setDisplayResolutionRequestBaseline] = useState("");

  const autoStartRequestedRef = useRef(false);
  const autoStartInFlightRef  = useRef(false);
  const streamStartedByThisViewRef = useRef(false);
  const staleRestartInFlightRef = useRef(false);
  const lastStaleRestartAtRef = useRef(0);
  const displayChangeRestartInFlightRef = useRef(false);
  const lastDisplayChangeRestartAtRef = useRef(0);
  const lastDisplayRuntimeSignatureRef = useRef("");

  const theme    = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const { user } = useAuth();
  const role = user?.role || "";
  const isSuperadmin = role === "superadmin";
  const isViewer = role === "viewer";
  const canControlStream = ["superadmin", "admin", "bruger"].includes(role);
  const canManageDisplaySettings = ["superadmin", "admin"].includes(role);
  const showDebug = isSuperadmin;
  // Den gamle globale clientOnline-status tilhører det samlede ClientFlow-system
  // og må ikke blokere Livestream v2. Hvis HLS faktisk er klar, er Livestream
  // tilgængelig, selv hvis den gamle globale status stadig siger offline.
  const livestreamVisuallyOffline = clientOnline === false && !serverReady && !manifestReady;


  /*
    VIGTIGT:
    Tidligere brugte komponenten ENTEN parent streamKey ELLER localRefreshKey.
    Hvis parent altid sender streamKey, havde lokal refresh og automatisk HLS-retry
    ingen effekt, fordi effectiveRefreshKey ikke ændrede sig.

    Nu kombineres begge, så både parent-refresh, manuel refresh og auto-reconnect
    tvinger HLS/health-effekterne til at starte forfra.
  */
  const effectiveRefreshKey = useMemo(() => {
    const parentKey = streamKey ?? "none";
    return `${parentKey}:${localRefreshKey}`;
  }, [streamKey, localRefreshKey]);

  const displayRuntimeSignature = useMemo(
    () => getDisplayRuntimeSignature(client),
    [client]
  );

  const livestreamAspectRatio = useMemo(
    () => getLivestreamAspectRatio(client),
    [client]
  );

  const resetStreamState = useCallback(() => {
    if (hlsRef.current) {
      try { hlsRef.current.destroy(); } catch {}
      hlsRef.current = null;
    }

    const video = videoRef.current;
    if (video) {
      try {
        video.pause();
        video.removeAttribute("src");
        video.load();
      } catch {}
    }

    setServerReady(false);
    setManifestReady(false);
    setError("");
    setBuffering(false);
    setCurrentSegNum(null);
    setFragDuration(2);
    setLastSegNum(null);
    setLastSegmentLag(null);
    setLastSegmentTimestamp(null);
    setLastFetched(null);
    setStreamStale(false);
    setHealthInfo(null);
    setAutoStartError("");
  }, []);


  const ensureStreamStarted = useCallback(async (reason = "auto", { force = false } = {}) => {
    if (!canControlStream) return false;
    if (!clientId || clientOnline === false) return false;
    if (!force && autoStartRequestedRef.current) return false;
    if (autoStartInFlightRef.current) return false;

    autoStartRequestedRef.current = true;
    autoStartInFlightRef.current = true;
    setAutoStartError("");
    const statusText =
      reason === "manual_refresh"
        ? "Genstarter livestream …"
        : reason === "stale_watchdog"
        ? "Livestream stod stille — genstarter …"
        : "Starter livestream …";
    setAutoStartStatus(statusText);

    try {
      const commandResult = await sendLivestreamCommand(clientId, "livestream_start", { source: reason });
      if (!commandResult?.already_requested && !commandResult?.alreadyRequested) {
        streamStartedByThisViewRef.current = true;
      }
      if (typeof onCommandSent === "function") {
        try {
          onCommandSent({ action: "livestream_start", reason });
        } catch {
          // Ignorer callback-fejl — livestream bestillingen er allerede sendt.
        }
      }
      setAutoStartStatus("Livestream er bestilt — venter på segmenter …");
      return true;
    } catch (err) {
      autoStartRequestedRef.current = false;
      setAutoStartStatus("");
      setAutoStartError(err?.message || "Kunne ikke starte livestream.");
      return false;
    } finally {
      autoStartInFlightRef.current = false;
    }
  }, [canControlStream, clientId, clientOnline, onCommandSent]);

  const restartStreamAfterDisplayChange = useCallback(async () => {
    if (!clientId || clientOnline === false) return;

    const now = Date.now();
    if (displayChangeRestartInFlightRef.current || now - lastDisplayChangeRestartAtRef.current < 5000) {
      return;
    }

    displayChangeRestartInFlightRef.current = true;
    lastDisplayChangeRestartAtRef.current = now;

    setAutoStartError("");
    setAutoStartStatus("Genstarter livestream efter skærmændring …");

    autoStartRequestedRef.current = false;
    autoStartInFlightRef.current = false;
    resetStreamState();
    setRefreshing(true);

    try {
      // Ubuntu-controlleren/supervisoren ejer producer-generation og HLS-reset
      // efter displayændring. Browseren nulstiller playerstate og sender kun et
      // idempotent ensure-start som fallback; viewer-presence ejer normal lifecycle.
      await ensureStreamStarted("display_resolution_changed", { force: true });
    } catch {
      // ensureStreamStarted håndterer selv synlig fejltekst.
    }

    setLocalRefreshKey((k) => k + 1);

    if (typeof onRestartStream === "function") {
      try { onRestartStream(); } catch {}
    }

    window.setTimeout(() => {
      displayChangeRestartInFlightRef.current = false;
      setRefreshing(false);
    }, 1500);
  }, [
    clientId,
    clientOnline,
    ensureStreamStarted,
    onRestartStream,
    resetStreamState,
  ]);

  useEffect(() => {
    autoStartRequestedRef.current = false;
    autoStartInFlightRef.current = false;
    streamStartedByThisViewRef.current = false;
    viewerLeaveSentRef.current = false;
    if (hiddenInactivityTimerRef.current) {
      window.clearTimeout(hiddenInactivityTimerRef.current);
      hiddenInactivityTimerRef.current = null;
    }
    lastDisplayRuntimeSignatureRef.current = "";
    setInactivityStopped(false);
    setInactivityStopMessage("");
    setAutoStartStatus("");
    setAutoStartError("");
  }, [clientId]);

  // Viewer-presence ejer Livestream-v2 lifecycle server-side. Browseren sender
  // kun presence/leave; backend bestemmer generation, grace og stop.


  const wasOnlineRef = useRef(clientOnline !== false);

  /*
    Når klienten går offline, skal gammel HLS-instans og gamle segment-data ryddes.
    Når klienten kommer online igen efter shutdown/reboot, skal streamen starte helt
    forfra automatisk uden at brugeren trykker refresh.

    Vigtigt: Ved hurtige reboot kan backend nå at holde klienten "online" via
    online-timeout, så parent-komponenten har også en uptime-reset watchdog som
    bumper streamKey. Denne effekt håndterer de tilfælde, hvor online faktisk
    skifter false -> true.
  */
  useEffect(() => {
    const isOnline = clientOnline !== false;
    const wasOnline = wasOnlineRef.current;
    wasOnlineRef.current = isOnline;

    if (!isOnline) {
      autoStartRequestedRef.current = false;
      autoStartInFlightRef.current = false;
      resetStreamState();
      return undefined;
    }

    if (!wasOnline && isOnline) {
      let cancelled = false;
      autoStartRequestedRef.current = false;
      autoStartInFlightRef.current = false;
      setInactivityStopped(false);
      setInactivityStopMessage("");
      resetStreamState();
      setRefreshing(true);
      setAutoStartError("");
      setAutoStartStatus("Klienten er online igen — genstarter livestream …");

      async function restartAfterReconnect() {
        try {
          // Ryd ikke serverens HLS-filer ved almindelig reconnect. Segmentnavne
          // genbruges fra 00000 efter reset og kan give cache/manifest-problemer
          // i browseren. Genindlæs kun HLS-afspilleren lokalt.
          if (!cancelled) {
            await ensureStreamStarted("client_reconnected", { force: true });
            setLocalRefreshKey((k) => k + 1);
            if (typeof onRestartStream === "function") {
              try { onRestartStream(); } catch {}
            }
          }
        } finally {
          window.setTimeout(() => {
            if (!cancelled) setRefreshing(false);
          }, 1200);
        }
      }

      restartAfterReconnect();
      return () => { cancelled = true; };
    }

    return undefined;
  }, [clientId, clientOnline, ensureStreamStarted, onRestartStream, resetStreamState]);

  // -------------------------------------------------------------------------
  // Viewer-owned lifecycle: 10s heartbeat, 30s lease, 30s backend grace.
  // Hidden/page-leave/unmount sends leave immediately; the backend is the
  // lifecycle authority and coalesces start/stop across multiple viewers.
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!clientId || inactivityStopped) return undefined;

    let stopped = false;
    viewerLeaveSentRef.current = false;

    const sendHeartbeat = async () => {
      if (stopped || viewerLeaveSentRef.current || document.visibilityState === "hidden") return;
      try {
        const resp = await fetch(`${apiUrl}/api/livestream-v2/hls/${encodeURIComponent(clientId)}/viewer-heartbeat`, {
          method: "POST",
          credentials: "include",
          headers: {
            ...getAuthHeaders(),
            "Content-Type": "application/json",
            accept: "application/json",
          },
          body: JSON.stringify({
            viewer_id: viewerIdRef.current,
            source: "client_details_livestream",
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!resp.ok) {
          let detail = "";
          try {
            const payload = await resp.json();
            detail = String(payload?.detail || payload?.message || "");
          } catch {}
          throw new Error(detail || `Viewer-heartbeat fejlede (${resp.status})`);
        }
        const payload = await resp.json().catch(() => null);
        setAutoStartError("");
        if (payload?.start_enqueued) {
          setAutoStartStatus("Livestream starter automatisk — venter på segmenter …");
        }
      } catch (err) {
        // Browseren må ikke overtage lifecycle-authority, men heartbeat-fejl skal
        // være synlige; ellers ser en 401/403/500 ud som en producer-fejl.
        setAutoStartError(err?.message || "Viewer-heartbeat kunne ikke registreres.");
      }
    };

    const sendLeaveOnce = (source = "client_details_livestream_leave") => {
      if (viewerLeaveSentRef.current) return;
      viewerLeaveSentRef.current = true;
      sendViewerLeave(clientId, viewerIdRef.current, {
        keepalive: true,
        source,
      });
    };

    const reactivateViewer = () => {
      if (stopped || document.visibilityState === "hidden") return;
      viewerLeaveSentRef.current = false;
      sendHeartbeat();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        sendLeaveOnce("client_details_livestream_hidden");
      } else {
        reactivateViewer();
      }
    };

    if (document.visibilityState === "hidden") {
      sendLeaveOnce("client_details_livestream_hidden_mount");
    } else {
      sendHeartbeat();
    }

    const interval = window.setInterval(() => {
      if (document.visibilityState !== "hidden") sendHeartbeat();
    }, VIEWER_HEARTBEAT_MS);
    const onFocus = () => reactivateViewer();
    const onFullscreenChange = () => {
      if (document.visibilityState !== "hidden") sendHeartbeat();
    };
    const onPageHide = () => sendLeaveOnce("client_details_livestream_pagehide");
    const onBeforeUnload = () => sendLeaveOnce("client_details_livestream_beforeunload");

    window.addEventListener("focus", onFocus);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("webkitfullscreenchange", onFullscreenChange);

    return () => {
      stopped = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      document.removeEventListener("webkitfullscreenchange", onFullscreenChange);
      sendLeaveOnce("client_details_livestream_unmount");
    };
  }, [clientId, inactivityStopped]);

  // -------------------------------------------------------------------------
  // Poll /health
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!clientId || inactivityStopped) return;
    setServerReady(false);
    setStreamStale(false);
    let stop = false;

    async function pollUntilReady() {
      while (!stop) {
        try {
          const resp = await fetch(`${apiUrl}/api/hls/${clientId}/health`, {
            credentials: "include",
            headers: getAuthHeaders(),
            signal: AbortSignal.timeout(8000),
          });
          if (resp.ok) {
            const data = await resp.json();
            if (!stop) setHealthInfo(data || null);
            if (data.has_segments && !data.is_stale) {
              if (!stop) {
                setServerReady(true);
                setStreamStale(false);
                setAutoStartStatus("");
                setAutoStartError("");
              }
            } else if (!stop) {
              // Health er en vedvarende readiness-observation. Hvis backend/HLS
              // forsvinder efter at have været klar (fx backend restart), skal
              // HLS-effekten afmonteres og først oprettes igen, når friske
              // segmenter findes på den nye backend-proces/generation.
              setServerReady(false);
              setStreamStale(data.has_segments && data.is_stale);
            }

            // Viewer-heartbeat ejer nu auto-start via backendens Livestream-v2
            // lifecycle. Health-polling må kun observere HLS og må ikke sende
            // konkurrerende startkommandoer.
          }
        } catch {
          if (!stop) {
            setServerReady(false);
            setHealthInfo((prev) => prev || { online: false, message: "Kunne ikke hente stream-status" });
          }
        }
        if (!stop) await new Promise(res => setTimeout(res, HEALTH_POLL_MS));
      }
    }

    pollUntilReady();
    return () => { stop = true; };
  }, [clientId, effectiveRefreshKey, inactivityStopped]);

  // -------------------------------------------------------------------------
  // HLS.js lifecycle
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!clientId || !serverReady || inactivityStopped) return undefined;
    setManifestReady(false);
    setError("");
    setCurrentSegNum(null);
    setLastSegNum(null);

    const video = videoRef.current;
    if (!video) return undefined;

    const hlsParams = new URLSearchParams();
    hlsParams.set("_kiosk_refresh", String(effectiveRefreshKey));
    hlsParams.set("_ts", String(Date.now()));
    const hlsUrl = `${apiUrl}/hls/${clientId}/index.m3u8?${hlsParams.toString()}`;

    let disposed = false;
    let activeHls = null;
    let fatalErrorTimeout = null;
    let playTimeout = null;
    let nativeLoadedHandler = null;

    const resetVideo = () => {
      try {
        video.pause();
        video.removeAttribute("src");
        video.load();
      } catch {}
    };

    const initialisePlayback = async () => {
      try {
        const { default: Hls } = await import("hls.js");
        if (disposed) return;

        if (Hls.isSupported()) {
          const hls = new Hls({
            // Vi bruger almindelig HLS med korte segmenter, ikke LL-HLS.
            // liveSyncDuration holder browseren tættere på live edge end den gamle 3x8s-buffer.
            liveSyncDuration: HLS_LIVE_SYNC_SECONDS,
            liveMaxLatencyDuration: HLS_MAX_LATENCY_SECONDS,
            initialLiveManifestSize: HLS_INITIAL_MANIFEST_SEGMENTS,
            maxBufferLength: 8,
            maxMaxBufferLength: 16,
            backBufferLength: 12,
            maxLiveSyncPlaybackRate: 1.15,
            enableWorker: true,
            startLevel: -1,
            lowLatencyMode: false,
            manifestLoadPolicy: {
              default: {
                maxTimeToFirstByteMs: 8000,
                maxLoadTimeMs: 12000,
                timeoutRetry: { maxNumRetry: 2, retryDelayMs: 1000, maxRetryDelayMs: 4000 },
                errorRetry: { maxNumRetry: 4, retryDelayMs: 1000, maxRetryDelayMs: 8000 },
              },
            },
            playlistLoadPolicy: {
              default: {
                maxTimeToFirstByteMs: 8000,
                maxLoadTimeMs: 12000,
                timeoutRetry: { maxNumRetry: 2, retryDelayMs: 1000, maxRetryDelayMs: 4000 },
                errorRetry: { maxNumRetry: 4, retryDelayMs: 1000, maxRetryDelayMs: 8000 },
              },
            },
            fragLoadPolicy: {
              default: {
                maxTimeToFirstByteMs: 10000,
                maxLoadTimeMs: 20000,
                timeoutRetry: { maxNumRetry: 2, retryDelayMs: 1000, maxRetryDelayMs: 5000 },
                errorRetry: { maxNumRetry: 5, retryDelayMs: 1000, maxRetryDelayMs: 12000 },
              },
            },
            xhrSetup: (xhr) => {
              const headers = getAuthHeaders();
              if (headers.Authorization) {
                xhr.setRequestHeader("Authorization", headers.Authorization);
              }
              xhr.withCredentials = true;
            },
          });

          activeHls = hls;
          hlsRef.current = hls;
          video.muted = true;
          video.autoplay = true;
          video.playsInline = true;
          hls.attachMedia(video);

          hls.on(Hls.Events.MEDIA_ATTACHED, () => {
            if (!disposed) hls.loadSource(hlsUrl);
          });

          hls.on(Hls.Events.MANIFEST_PARSED, () => {
            if (disposed) return;
            lastHlsProgressAtRef.current = Date.now();
            setManifestReady(true);
            setError("");
            playTimeout = window.setTimeout(() => video.play().catch(() => {}), 100);
          });

          hls.on(Hls.Events.MANIFEST_LOADED, () => {
            lastHlsProgressAtRef.current = Date.now();
          });

          hls.on(Hls.Events.FRAG_LOADED, () => {
            lastHlsProgressAtRef.current = Date.now();
          });

          hls.on(Hls.Events.LEVEL_LOADED, () => {
            try {
              const livePos = hls.liveSyncPosition;
              if (Number.isFinite(livePos) && Number.isFinite(video.currentTime)) {
                const behind = livePos - video.currentTime;
                if (behind > HLS_CATCH_UP_SEEK_SECONDS) {
                  video.currentTime = Math.max(0, livePos - 0.25);
                }
              }
            } catch {}
          });

          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (disposed) return;
            if (data.fatal) {
              try {
                if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
                  hls.recoverMediaError();
                  return;
                }
                if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                  // Hls.js kan blive hængende på en død backend-proces, selv
                  // efter at /health og HLS-filer er tilbage. Forsøg først den
                  // billige startLoad-recovery, men planlæg altid en bounded
                  // player-recreation som fallback. effectiveRefreshKey giver
                  // en ny manifest-URL med cache-buster og frisk Hls-instans.
                  hls.startLoad(-1);
                  if (fatalErrorTimeout) window.clearTimeout(fatalErrorTimeout);
                  fatalErrorTimeout = window.setTimeout(() => {
                    if (!disposed) setLocalRefreshKey((key) => key + 1);
                  }, AUTO_RECONNECT_DELAY_MS);
                  return;
                }
              } catch {}

              setError("Streamforbindelsen blev afbrudt. Genopretter afspilleren …");
              hls.destroy();
              if (hlsRef.current === hls) hlsRef.current = null;
              activeHls = null;
              resetVideo();
              setManifestReady(false);
              setServerReady(false);
              if (fatalErrorTimeout) window.clearTimeout(fatalErrorTimeout);
              fatalErrorTimeout = window.setTimeout(
                () => setLocalRefreshKey((key) => key + 1),
                AUTO_RECONNECT_DELAY_MS,
              );
            } else if (!["bufferStalledError", "bufferNudgeOnStall", "fragLoadError", "levelLoadError"].includes(data.details)) {
              console.warn("[HLS Error]", data.details);
            }
          });

          hls.on(Hls.Events.FRAG_CHANGED, (_event, data) => {
            if (disposed) return;
            lastHlsProgressAtRef.current = Date.now();
            if (data?.frag && typeof data.frag.sn === "number") {
              setCurrentSegNum(data.frag.sn);
              if (data.frag.duration > 0) setFragDuration(data.frag.duration);
              setError("");
            }
            try {
              const livePos = hls.liveSyncPosition;
              if (Number.isFinite(livePos) && Number.isFinite(video.currentTime)) {
                const behind = livePos - video.currentTime;
                if (behind > HLS_CATCH_UP_SEEK_SECONDS) {
                  video.currentTime = Math.max(0, livePos - 0.25);
                }
              }
            } catch {}
          });
          return;
        }

        if (video.canPlayType("application/vnd.apple.mpegurl")) {
          video.crossOrigin = "use-credentials";
          video.src = hlsUrl;
          video.muted = true;
          video.autoplay = true;
          video.playsInline = true;
          nativeLoadedHandler = () => {
            if (disposed) return;
            lastHlsProgressAtRef.current = Date.now();
            setManifestReady(true);
            playTimeout = window.setTimeout(() => video.play().catch(() => {}), 100);
          };
          video.addEventListener("loadedmetadata", nativeLoadedHandler, { once: true });
          return;
        }

        setError("Browseren understøtter ikke HLS-afspilning.");
      } catch {
        if (!disposed) setError("Kunne ikke indlæse HLS-afspilleren.");
      }
    };

    initialisePlayback();

    return () => {
      disposed = true;
      if (fatalErrorTimeout) window.clearTimeout(fatalErrorTimeout);
      if (playTimeout) window.clearTimeout(playTimeout);
      if (nativeLoadedHandler) video.removeEventListener("loadedmetadata", nativeLoadedHandler);
      if (activeHls) {
        activeHls.destroy();
        if (hlsRef.current === activeHls) hlsRef.current = null;
      }
      resetVideo();
      setManifestReady(false);
    };
  }, [clientId, effectiveRefreshKey, serverReady, inactivityStopped]);

  // -------------------------------------------------------------------------
  // Backend polling — hvert 2s
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!clientId || !manifestReady || inactivityStopped) return;
    let stop = false;

    async function pollLastSegment() {
      while (!stop) {
        try {
          const resp = await fetchWithRetry(
            `${apiUrl}/api/hls/${clientId}/last-segment-info?nocache=${Date.now()}`,
            { credentials: "include" }
          );
          if (resp.ok) {
            const data = await resp.json();
            setLastFetched(new Date());
            const num = extractSegNum(data.segment);
            if (num !== null) setLastSegNum(num);
            if (data.timestamp) {
              setLastSegmentTimestamp(data.timestamp);
              setLastSegmentLag((Date.now() - new Date(data.timestamp).getTime()) / 1000);
            } else {
              setLastSegmentTimestamp(null);
              setLastSegmentLag(null);
            }
          }
        } catch {
          setLastSegmentTimestamp(null);
          setLastSegmentLag(null);
        }
        await new Promise(res => setTimeout(res, LAST_SEGMENT_POLL_MS));
      }
    }

    pollLastSegment();
    return () => { stop = true; };
  }, [clientId, manifestReady, effectiveRefreshKey, inactivityStopped]);

  // -------------------------------------------------------------------------
  // Stale watchdog — genstart HLS hvis segmenter stopper efter boot/reboot
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!clientId || !manifestReady || inactivityStopped) return undefined;

    let stopped = false;

    async function restartStaleStream(reasonAge) {
      if (stopped || staleRestartInFlightRef.current) return;

      const now = Date.now();
      if (now - lastStaleRestartAtRef.current < STALE_SEGMENT_RESTART_COOLDOWN_MS) {
        return;
      }

      staleRestartInFlightRef.current = true;
      lastStaleRestartAtRef.current = now;

      setStreamStale(true);
      setAutoStartError("");
      setAutoStartStatus(`Livestream stod stille (${Math.round(reasonAge)} sek.) — genindlæser afspilleren …`);
      setRefreshing(true);

      try {
        resetStreamState();

        // Browseren genindlæser kun HLS-playeren. Klientens lokale supervisor
        // overvåger producer, uploader og grafisk sessionsfingerprint og ejer
        // alle proces-restarts. Det forhindrer konkurrerende recovery-kommandoer.
        setLocalRefreshKey((k) => k + 1);

        if (typeof onRestartStream === "function") {
          try { onRestartStream(); } catch {}
        }
      } catch (err) {
        setAutoStartError(err?.message || "Kunne ikke genindlæse livestream-afspilleren.");
      } finally {
        window.setTimeout(() => {
          if (!stopped) setRefreshing(false);
        }, 1200);
        staleRestartInFlightRef.current = false;
      }
    }

    const check = () => {
      if (stopped || !manifestReady) return;

      const timestampMs = lastSegmentTimestamp
        ? new Date(lastSegmentTimestamp).getTime()
        : null;

      const ageFromTimestamp = Number.isFinite(timestampMs)
        ? (Date.now() - timestampMs) / 1000
        : null;

      const ageFromLag = Number.isFinite(lastSegmentLag)
        ? Number(lastSegmentLag)
        : null;

      const age = Math.max(
        ageFromTimestamp ?? 0,
        ageFromLag ?? 0
      );

      if (age >= STALE_SEGMENT_RESTART_AFTER_SECONDS) {
        restartStaleStream(age);
      }
    };

    check();
    const timer = window.setInterval(check, STALE_WATCHDOG_POLL_MS);

    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [
    clientId,
    manifestReady,
    lastSegmentTimestamp,
    lastSegmentLag,
    effectiveRefreshKey,
    inactivityStopped,
    onRestartStream,
    resetStreamState,
  ]);

  // -------------------------------------------------------------------------
  // Playback watchdog — især vigtig i fullscreen
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!clientId || !manifestReady || inactivityStopped) return undefined;

    const timer = window.setInterval(() => {
      const video = videoRef.current;
      const hls = hlsRef.current;
      if (!video || !hls) return;

      const now = Date.now();
      const currentTime = Number(video.currentTime || 0);
      const progressed = Math.abs(currentTime - lastVideoTimeRef.current) > 0.05;
      lastVideoTimeRef.current = currentTime;

      try {
        const livePos = hls.liveSyncPosition;
        if (Number.isFinite(livePos) && Number.isFinite(video.currentTime)) {
          const behind = livePos - video.currentTime;
          if (behind > HLS_CATCH_UP_SEEK_SECONDS || (!progressed && behind > 4)) {
            video.currentTime = Math.max(0, livePos - 0.75);
            video.play?.().catch(() => {});
          }
        }

        const noHlsProgressMs = lastHlsProgressAtRef.current ? now - lastHlsProgressAtRef.current : 0;
        if (noHlsProgressMs > 25_000) {
          // Genstart kun playeren. Stop/start ikke klientens producer her.
          setLocalRefreshKey(k => k + 1);
          lastHlsProgressAtRef.current = now;
        }
      } catch {}
    }, FULLSCREEN_WATCHDOG_MS);

    return () => window.clearInterval(timer);
  }, [clientId, manifestReady, inactivityStopped]);

  // -------------------------------------------------------------------------
  // Forsinkelsesberegning
  // -------------------------------------------------------------------------
  const computedLag = useMemo(() => {
    if (lastSegNum != null && currentSegNum != null && lastSegmentLag != null) {
      const segsBehind = lastSegNum - currentSegNum;
      const lag = segsBehind * fragDuration + lastSegmentLag;
      return lag >= 0 ? Math.round(lag) : null;
    }
    if (lastSegmentLag != null) {
      return Math.round(lastSegmentLag);
    }
    return null;
  }, [lastSegNum, currentSegNum, fragDuration, lastSegmentLag]);

  // -------------------------------------------------------------------------
  // Handlers
  // -------------------------------------------------------------------------
  const handleRefreshClick = async () => {
    if (refreshing || !clientId) return;

    autoStartRequestedRef.current = false;
    autoStartInFlightRef.current = false;
    viewerLeaveSentRef.current = false;
    setInactivityStopped(false);
    setInactivityStopMessage("");
    setRefreshing(true);
    setError("");
    setAutoStartStatus("Genindlæser HLS-afspiller …");

    try {
      // Genindlæs kun browserens HLS-player. Ryd ikke backendens segmenter her:
      // i fullscreen/reload-scenarier kan server-reset få browseren til at hente
      // gamle cachede segment_00000.ts/segment_00001.ts eller efterlade et tomt manifest.
      resetStreamState();
      setServerReady(true);
      setLocalRefreshKey(k => k + 1);

      // Start kun streamen, hvis manifestet mangler helt. Stale producer/uploader
      // recovery ejes af klientens lokale supervisor.
      if (!manifestReady) {
        await ensureStreamStarted("manual_refresh", { force: true });
      }

      if (typeof onRestartStream === "function") {
        try { onRestartStream(); } catch {}
      }
    } catch (err) {
      setError(err?.message || "Kunne ikke genindlæse livestream.");
    } finally {
      window.setTimeout(() => {
        setRefreshing(false);
        setAutoStartStatus("");
      }, 800);
    }
  };

  const handleFullscreen = () => {
    const el = videoContainerRef.current || videoRef.current;
    if (!el) return;
    if      (el.requestFullscreen)       el.requestFullscreen();
    else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    else if (el.msRequestFullscreen)     el.msRequestFullscreen();

    // Fullscreen kan få browseren til at pause/nudge video. Hold HLS tæt på live edge.
    window.setTimeout(() => {
      try {
        const video = videoRef.current;
        const hls = hlsRef.current;
        if (hls?.liveSyncPosition && video) {
          video.currentTime = Math.max(0, hls.liveSyncPosition - 0.5);
          video.play?.().catch(() => {});
        }
      } catch {}
    }, 500);
  };

  useEffect(() => {
    if (!showControls) return;
    const t = setTimeout(() => setShowControls(false), 2200);
    return () => clearTimeout(t);
  }, [showControls]);

  function handleVideoWaiting() { setBuffering(true);  }
  function handleVideoPlaying() { setBuffering(false); }
  function handleVideoCanPlay() { setBuffering(false); }

  const lagStatus       = getLagStatus(manifestReady ? computedLag : null);
  const disabledOverlay = livestreamVisuallyOffline ? { opacity: 0.65 } : {};

  const loadingText = inactivityStopped
    ? (inactivityStopMessage || INACTIVITY_STOP_MESSAGE)
    : autoStartError
    ? autoStartError
    : autoStartStatus
      ? autoStartStatus
      : streamStale
        ? "Stream er gået ned — venter på genstart …"
        : !serverReady ? "Venter på at stream starter …"
        : "Forbinder til stream …";

  const displayResolutionStatusNorm = normalizeDisplayResolutionStatus(client?.display_resolution_status);
  const displayResolutionMeta = useMemo(
    () => getDisplayResolutionStatusMeta(
      client?.display_resolution_status,
      client?.display_resolution_preset || "auto",
      client?.display_resolution_error || "",
      client?.display_resolution_action || null
    ),
    [
      client?.display_resolution_status,
      client?.display_resolution_preset,
      client?.display_resolution_error,
      client?.display_resolution_action,
    ]
  );
  const currentDisplayReport = useMemo(
    () => formatCurrentDisplayResolution(client),
    [client]
  );
  const displayResolutionBusy =
    settingsSaving || displayResolutionWatching || displayResolutionMeta.busy;

  const displayResolutionOptions = useMemo(
    () => getClientDisplayResolutionOptions(client),
    [client]
  );

  const selectedDisplayPreset = useMemo(
    () => findDisplayResolutionOption(settingsForm.preset, displayResolutionOptions),
    [settingsForm.preset, displayResolutionOptions]
  );
  const selectedDisplayIsAuto = selectedDisplayPreset.value === "auto";
  const selectedDisplayWidth = selectedDisplayIsAuto
    ? null
    : parseOptionalNumber(settingsForm.width);
  const selectedDisplayHeight = selectedDisplayIsAuto
    ? null
    : parseOptionalNumber(settingsForm.height);
  const selectedDisplayRefreshRate = selectedDisplayIsAuto
    ? null
    : parseOptionalNumber(settingsForm.refreshRate);

  const selectedResolutionDescription = selectedDisplayIsAuto
    ? "Auto-detekter skærmstørrelse"
    : formatResolutionLabel(selectedDisplayWidth, selectedDisplayHeight, selectedDisplayRefreshRate);

  const currentDisplayWidth = parseOptionalNumber(client?.display_resolution_current_width);
  const currentDisplayHeight = parseOptionalNumber(client?.display_resolution_current_height);
  const currentDisplayRefreshRate = parseOptionalNumber(client?.display_resolution_current_refresh_rate);
  const hasCurrentDisplayDimensions = Number.isFinite(currentDisplayWidth) && Number.isFinite(currentDisplayHeight);

  const selectedMatchesCurrentDisplay =
    !selectedDisplayIsAuto &&
    selectedDisplayWidth === currentDisplayWidth &&
    selectedDisplayHeight === currentDisplayHeight &&
    (
      selectedDisplayRefreshRate === null ||
      currentDisplayRefreshRate === null ||
      sameOptionalNumber(selectedDisplayRefreshRate, currentDisplayRefreshRate)
    );

  const selectedDisplayDiffersFromCurrent =
    !selectedDisplayIsAuto &&
    hasCurrentDisplayDimensions &&
    !selectedMatchesCurrentDisplay;

  const configuredDisplayPreset = client?.display_resolution_preset || "auto";
  const configuredDisplayPresetObj = findDisplayResolutionOption(configuredDisplayPreset, displayResolutionOptions);
  const configuredDisplayMode = String(
    client?.display_resolution_mode || configuredDisplayPresetObj.mode || "auto"
  ).toLowerCase();
  const configuredDisplayWidth = parseOptionalNumber(
    client?.display_resolution_width ?? configuredDisplayPresetObj.width
  );
  const configuredDisplayHeight = parseOptionalNumber(
    client?.display_resolution_height ?? configuredDisplayPresetObj.height
  );
  const configuredDisplayRefreshRate = parseOptionalNumber(client?.display_resolution_refresh_rate);

  const selectedMatchesConfiguredDisplay = selectedDisplayIsAuto
    ? configuredDisplayMode === "auto" && configuredDisplayPreset === "auto"
    : configuredDisplayMode === "fixed" &&
      configuredDisplayWidth === selectedDisplayWidth &&
      configuredDisplayHeight === selectedDisplayHeight &&
      sameOptionalNumber(configuredDisplayRefreshRate, selectedDisplayRefreshRate);

  const selectedDisplayHasValidFixedSelection =
    !selectedDisplayIsAuto &&
    Number.isFinite(selectedDisplayWidth) &&
    Number.isFinite(selectedDisplayHeight);

  const selectedDisplayAlreadyActive =
    selectedDisplayHasValidFixedSelection &&
    hasCurrentDisplayDimensions &&
    selectedMatchesCurrentDisplay;

  const selectedDisplayHasActualChange =
    settingsTouched &&
    selectedDisplayHasValidFixedSelection &&
    (
      !hasCurrentDisplayDimensions ||
      !selectedMatchesCurrentDisplay
    );

  // Behold konstanten som false, så eksisterende status-helper stadig kan kaldes
  // uden at vi viser et separat "Gem som standard"-flow. I denne dialog gemmer vi
  // kun, når brugeren faktisk vælger en anden fysisk skærmindstilling.
  const selectedDisplayCanBeSavedAsFixed = false;

  // Brugeren skal selv have ændret formularen, før vi tilbyder "Gem og anvend".
  // Auto-detektering ved dialogåbning skal kun opdatere aktuel status, ikke oprette
  // en falsk "ugemt ændring".
  const displaySaveButtonLabel = settingsSaving
    ? "Sender…"
    : displayResolutionStatusNorm === "error" && selectedDisplayHasActualChange
    ? "Prøv igen"
    : selectedDisplayHasActualChange
    ? "Gem og anvend"
    : "Ingen ændringer";

  const displaySaveButtonDisabled =
    settingsSaving ||
    displayResolutionMeta.busy ||
    displayResolutionWatching ||
    !clientId ||
    clientOnline === false ||
    !selectedDisplayHasActualChange;

  const optimisticDisplayResolutionMeta = displayResolutionWatching
    ? getOptimisticDisplayResolutionMeta(displayResolutionWatchingAction, false)
    : null;

  const displayResolutionUiMeta = displayResolutionMeta.busy
    ? displayResolutionMeta
    : optimisticDisplayResolutionMeta || displayResolutionMeta;



  const currentDisplayDescription = currentDisplayReport;

  const streamOverlayMeta = useMemo(() => {
    if (livestreamVisuallyOffline) return null;

    const displayText = currentDisplayDescription && currentDisplayDescription !== "Ikke rapporteret endnu"
      ? currentDisplayDescription
      : null;

    const lagText = manifestReady && computedLag !== null
      ? (computedLag <= 3 ? "Live" : `${Math.round(computedLag)} sek. forsinkelse`)
      : null;

    const segmentText = lastSegNum !== null
      ? `segment ${lastSegNum}`
      : healthInfo?.latest_segment
      ? String(healthInfo.latest_segment).replace(/^segment[-_]/, "seg. ").replace(/\.(ts|m4s|mp4)$/i, "")
      : null;

    const healthMessage = healthInfo?.message || "";
    const healthAge = Number(healthInfo?.age_seconds);
    const healthAgeText = Number.isFinite(healthAge) && healthAge >= 0
      ? `sidste segment ${Math.round(healthAge)} sek. siden`
      : null;

    if (inactivityStopped) {
      return {
        severity: "warning",
        title: "Livestream stoppet",
        detail: inactivityStopMessage || INACTIVITY_STOP_MESSAGE,
        persistent: true,
      };
    }

    if (autoStartError || error) {
      return {
        severity: "error",
        title: "Livestream-fejl",
        detail: autoStartError || error,
        persistent: true,
      };
    }

    if (autoStartStatus) {
      return {
        severity: "info",
        title: autoStartStatus,
        detail: [displayText && `Skærm: ${displayText}`, healthMessage].filter(Boolean).join(" · "),
        persistent: true,
      };
    }

    if (streamStale) {
      return {
        severity: "error",
        title: "Stream er gået i stå",
        detail: healthAgeText || "Venter på automatisk genstart …",
        persistent: true,
      };
    }

    if (displayResolutionUiMeta.busy) {
      return {
        severity: "info",
        title: displayResolutionUiMeta.short || "Skærmændring behandles",
        detail: displayResolutionUiMeta.detail || displayText || "Afventer klienten …",
        persistent: true,
      };
    }

    if (buffering) {
      return {
        severity: "warning",
        title: "Buffering …",
        detail: [lagText, healthAgeText].filter(Boolean).join(" · ") || "Henter nye segmenter …",
        persistent: true,
      };
    }

    if (!serverReady || !manifestReady) {
      return {
        severity: "info",
        title: !serverReady ? "Venter på stream" : "Forbinder til stream",
        detail: healthMessage || "Afventer HLS-manifest og segmenter …",
        persistent: true,
      };
    }

    return {
      severity: "success",
      title: "Stream live",
      detail: [displayText && `Skærm: ${displayText}`, lagText, segmentText].filter(Boolean).join(" · "),
      persistent: false,
    };
  }, [
    autoStartError,
    autoStartStatus,
    buffering,
    livestreamVisuallyOffline,
    computedLag,
    currentDisplayDescription,
    displayResolutionUiMeta.busy,
    displayResolutionUiMeta.detail,
    displayResolutionUiMeta.short,
    error,
    healthInfo,
    inactivityStopMessage,
    inactivityStopped,
    lastSegNum,
    manifestReady,
    serverReady,
    streamStale,
  ]);

  const streamOverlaySx = useMemo(() => {
    const severity = streamOverlayMeta?.severity || "info";
    const palette = {
      success: { bg: "rgba(6,78,59,0.72)", border: "rgba(52,211,153,0.42)", dot: "#22c55e" },
      info:    { bg: "rgba(15,23,42,0.78)", border: "rgba(125,211,252,0.38)", dot: "#38bdf8" },
      warning: { bg: "rgba(113,63,18,0.78)", border: "rgba(251,191,36,0.45)", dot: "#f59e0b" },
      error:   { bg: "rgba(127,29,29,0.78)", border: "rgba(248,113,113,0.48)", dot: "#ef4444" },
    };
    return palette[severity] || palette.info;
  }, [streamOverlayMeta?.severity]);

  const openSettingsDialog = useCallback(() => {
    setSettingsForm(getInitialDisplaySettingsForm(client, displayResolutionOptions));
    setSettingsTouched(false);
    setSettingsMessage("");
    setSettingsError("");
    autoDetectOnOpenRef.current = true;
    setSettingsOpen(true);
  }, [client, displayResolutionOptions]);

  const handlePresetChange = useCallback((event) => {
    const value = event.target.value;
    const preset = findDisplayResolutionOption(value, displayResolutionOptions);
    setSettingsTouched(true);
    setSettingsForm((prev) => ({
      ...prev,
      preset: value,
      width: preset.width ? String(preset.width) : "",
      height: preset.height ? String(preset.height) : "",
      refreshRate: preset.refreshRate !== null && preset.refreshRate !== undefined ? String(preset.refreshRate) : "",
    }));
  }, [displayResolutionOptions]);

  const handleAutoDetectDisplayResolution = useCallback(async () => {
    if (!clientId || clientOnline === false || settingsSaving || displayResolutionMeta.busy || displayResolutionWatching) return;

    setSettingsSaving(true);
    setSettingsError("");
    setSettingsMessage("");

    try {
      setDisplayResolutionRequestBaseline(String(client?.display_resolution_updated_at || ""));
      await updateClient(clientId, {
        display_resolution_action: "detect",
      });

      setDisplayResolutionWatching(true);
      setDisplayResolutionWatchingAction("detect");
      setDisplayResolutionSawWorkingState(false);
      setSettingsMessage("");

      if (typeof onDisplayResolutionSettingsSaved === "function") {
        try { await onDisplayResolutionSettingsSaved(); } catch {}
      }
    } catch (err) {
      setSettingsError(err?.message || "Kunne ikke starte auto-detektering.");
    } finally {
      setSettingsSaving(false);
    }
  }, [
    clientId,
    clientOnline,
    settingsSaving,
    displayResolutionMeta.busy,
    displayResolutionWatching,
    client,
    onDisplayResolutionSettingsSaved,
  ]);

  useEffect(() => {
    if (!settingsOpen || !autoDetectOnOpenRef.current) return;

    autoDetectOnOpenRef.current = false;

    if (!clientId || settingsSaving || displayResolutionMeta.busy || displayResolutionWatching) {
      return;
    }

    handleAutoDetectDisplayResolution();
  }, [
    settingsOpen,
    clientId,
    settingsSaving,
    displayResolutionMeta.busy,
    displayResolutionWatching,
    handleAutoDetectDisplayResolution,
  ]);

  const handleSaveLivestreamSettings = useCallback(async () => {
    if (!clientId || displaySaveButtonDisabled) return;

    const preset = selectedDisplayPreset;
    const isAuto = selectedDisplayIsAuto;
    const width = selectedDisplayWidth;
    const height = selectedDisplayHeight;
    const refreshRate = selectedDisplayRefreshRate;

    if (!isAuto && (!Number.isFinite(width) || !Number.isFinite(height) || width < 320 || height < 240)) {
      setSettingsError("Bredde og højde skal være mindst 320×240 px.");
      return;
    }
    if (refreshRate !== null && (!Number.isFinite(refreshRate) || refreshRate < 1 || refreshRate > 240)) {
      setSettingsError("Refresh rate skal være mellem 1 og 240 Hz.");
      return;
    }

    setSettingsSaving(true);
    setSettingsError("");
    setSettingsMessage("");
    try {
      setDisplayResolutionRequestBaseline(String(client?.display_resolution_updated_at || ""));
      await updateClient(clientId, {
        display_resolution_preset: preset.source === "client" ? "custom" : preset.value,
        display_resolution_mode: isAuto ? "auto" : "fixed",
        display_resolution_width: isAuto ? null : width,
        display_resolution_height: isAuto ? null : height,
        display_resolution_refresh_rate: isAuto ? null : refreshRate,
        display_resolution_rotation: "normal",
        display_resolution_action: "apply",
      });
      setDisplayResolutionWatching(true);
      setDisplayResolutionWatchingAction("apply");
      setDisplayResolutionSawWorkingState(false);
      // Statusfeltet øverst i dialogen viser nu processen.
      // Undgå ekstra dobbeltbesked under formularen.
      setSettingsMessage("");
      if (typeof onDisplayResolutionSettingsSaved === "function") {
        try { await onDisplayResolutionSettingsSaved(); } catch {}
      }
    } catch (err) {
      setSettingsError(err?.message || "Kunne ikke gemme skærmindstillinger.");
    } finally {
      setSettingsSaving(false);
    }
  }, [
    clientId,
    displaySaveButtonDisabled,
    selectedDisplayPreset,
    selectedDisplayIsAuto,
    selectedDisplayWidth,
    selectedDisplayHeight,
    selectedDisplayRefreshRate,
    client,
    onDisplayResolutionSettingsSaved,
  ]);

  useEffect(() => {
    if (!clientId || clientOnline === false || !displayRuntimeSignature) return undefined;

    const previous = lastDisplayRuntimeSignatureRef.current;
    if (!previous) {
      lastDisplayRuntimeSignatureRef.current = displayRuntimeSignature;
      return undefined;
    }

    if (previous === displayRuntimeSignature) return undefined;

    lastDisplayRuntimeSignatureRef.current = displayRuntimeSignature;

    // Når klienten selv rapporterer en ny faktisk skærmopløsning efter xrandr,
    // skal livestream-visningen slippe gamle HLS-segmenter/manifest.
    // Vi gør det kun hvis streamen allerede har været aktiv, så en ren
    // auto-detektering ikke starter livestream unødigt.
    const streamHasBeenActive =
      serverReady ||
      manifestReady ||
      lastSegNum !== null ||
      Boolean(lastSegmentTimestamp);

    if (streamHasBeenActive) {
      restartStreamAfterDisplayChange();
    }

    return undefined;
  }, [
    clientId,
    clientOnline,
    displayRuntimeSignature,
    serverReady,
    manifestReady,
    lastSegNum,
    lastSegmentTimestamp,
    restartStreamAfterDisplayChange,
  ]);

  useEffect(() => {
    const isWorkingStatus =
      displayResolutionStatusNorm === "pending" ||
      displayResolutionStatusNorm === "applying";

    const isTerminalStatus =
      displayResolutionStatusNorm === "detected" ||
      displayResolutionStatusNorm === "applied" ||
      displayResolutionStatusNorm === "error";

    if (displayResolutionWatching && isWorkingStatus && !displayResolutionSawWorkingState) {
      setDisplayResolutionSawWorkingState(true);
    }

    const statusBelongsToCurrentRequest =
      displayResolutionSawWorkingState ||
      (
        !!client?.display_resolution_updated_at &&
        String(client.display_resolution_updated_at) !== String(displayResolutionRequestBaseline || "")
      );

    if (displayResolutionWatching && isTerminalStatus && statusBelongsToCurrentRequest) {
      const shouldRefreshStream =
        displayResolutionWatchingAction === "apply" &&
        displayResolutionStatusNorm === "applied";

      if (shouldRefreshStream) {
        restartStreamAfterDisplayChange();
      }

      if (displayResolutionWatchingAction === "detect" && displayResolutionStatusNorm === "detected") {
        setSettingsForm(getInitialDisplaySettingsForm(client));
        setSettingsTouched(false);
      }

      setDisplayResolutionWatching(false);
      setDisplayResolutionWatchingAction(null);
      setDisplayResolutionSawWorkingState(false);
      return undefined;
    }

    // Poll kun mens der faktisk kører en skærmproces.
    // Tidligere blev der poll'et hvert 1,5 sek. bare fordi dialogen var åben,
    // hvilket gav unødvendige silentRefresh-loops og ekstra renders.
    const shouldPoll =
      displayResolutionWatching ||
      isWorkingStatus;

    if (!shouldPoll || typeof onDisplayResolutionSettingsSaved !== "function") {
      return undefined;
    }

    let stopped = false;

    const refreshDisplayResolutionStatus = async () => {
      try {
        await onDisplayResolutionSettingsSaved();
      } catch {
        // Parent refresh-fejl skal ikke lukke dialogen eller vise falsk status.
      }
    };

    refreshDisplayResolutionStatus();
    const timer = window.setInterval(() => {
      if (!stopped) refreshDisplayResolutionStatus();
    }, 1500);

    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [
    displayResolutionWatching,
    displayResolutionWatchingAction,
    displayResolutionSawWorkingState,
    displayResolutionStatusNorm,
    displayResolutionRequestBaseline,
    client,
    onDisplayResolutionSettingsSaved,
    restartStreamAfterDisplayChange,
  ]);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <Card
      elevation={0}
      sx={{
        borderRadius: 2,
        p: { xs: 1.15, sm: 1.55 },
        background: "linear-gradient(180deg, rgba(2,6,23,0.40), rgba(15,23,42,0.28))",
        border: "1px solid rgba(148,163,184,0.12)",
        boxShadow: "none",
        color: "#e5eefb",
        ...disabledOverlay,
      }}
    >
      <Stack spacing={1.35}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={1.1}
          sx={{
            alignItems: { xs: "stretch", md: "center" },
            justifyContent: "space-between",
            p: { xs: 1.35, sm: 1.75 },
            borderRadius: 2,
            background: "rgba(15,23,42,0.42)",
            border: "1px solid rgba(148,163,184,0.16)"
          }}>
          <Stack
            direction="row"
            spacing={1}
            sx={{
              alignItems: "center",
              minWidth: 0
            }}>
            <Box sx={{
              width: isMobile ? 8 : 10,
              height: isMobile ? 8 : 10,
              borderRadius: "50%",
              bgcolor: livestreamVisuallyOffline ? "#64748b"
                : manifestReady ? "#22c55e"
                : streamStale ? "#ef4444"
                : serverReady ? "#f59e0b"
                : "#64748b",
              boxShadow: manifestReady && !livestreamVisuallyOffline ? "0 0 0 5px rgba(34,197,94,0.14)" : "none",
              flex: "0 0 auto",
            }} />
            <Box sx={{
              minWidth: 0
            }}>
              <Typography sx={{ fontWeight: 950, color: "#f8fafc", lineHeight: 1.05 }}>
                {livestreamVisuallyOffline
                  ? "Stream offline"
                  : manifestReady
                  ? "Stream live"
                  : streamStale
                  ? "Stream genstartes"
                  : serverReady
                  ? "Forbinder til stream"
                  : "Afventer stream"}
              </Typography>
              <Typography variant="body2" sx={{ color: livestreamVisuallyOffline ? "#cbd5e1" : lagStatus.color, mt: 0.2 }}>
                {livestreamVisuallyOffline ? "Klienten er offline — afventer Livestream v2" : lagStatus.text}
              </Typography>
            </Box>
          </Stack>

          <Stack
            direction="row"
            spacing={0.8}
            useFlexGap
            sx={{
              flexWrap: "wrap",
              alignItems: "center"
            }}>
            <Tooltip title={livestreamVisuallyOffline ? "Afventer Livestream v2" : "Genindlæs stream"}>
              <span>
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={refreshing ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                  onClick={handleRefreshClick}
                  disabled={refreshing || !clientId}
                  sx={{ borderRadius: 999, fontWeight: 850 }}
                >
                  Genindlæs
                </Button>
              </span>
            </Tooltip>


            {canManageDisplaySettings && (
              <Button
                size="small"
                variant="outlined"
                onClick={openSettingsDialog}
                disabled={!clientId}
                sx={{ borderRadius: 999, fontWeight: 850 }}
              >
                Skærmindstillinger
              </Button>
            )}
          </Stack>
        </Stack>

        {(error || autoStartError) && !livestreamVisuallyOffline && (
          <Alert severity="error" sx={{ borderRadius: 2 }}>
            {error || autoStartError}
          </Alert>
        )}

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: isSuperadmin || isViewer
              ? { xs: "minmax(0, 1fr) 320px", md: "minmax(0, 1fr) 320px", lg: "minmax(0, 1fr) 320px" }
              : { xs: "1fr", md: "1fr", lg: "1fr" },
            gap: { xs: 1.2, sm: 1.45, md: 1.55 },
            alignItems: "stretch",
            justifyContent: "stretch",
            width: "100%",
            maxWidth: "100%",
            mx: 0,
            "--stream-panel-height": { xs: "auto", md: "clamp(250px, 32vh, 340px)", lg: "clamp(260px, 32vh, 360px)" },
          }}
        >
        <Box
          sx={{
            position: "relative",
            width: "100%",
            maxWidth: "100%",
            justifySelf: "stretch",
            height: { xs: "auto", md: "var(--stream-panel-height)" },
            minHeight: { xs: 180, md: "var(--stream-panel-height)" },
            mx: 0,
            borderRadius: 2,
            overflow: "hidden",
            border: "1px solid rgba(148,163,184,0.16)",
            background: "#000",
          }}
          onMouseMove={() => setShowControls(true)}
          onMouseLeave={() => setShowControls(false)}
          tabIndex={0}
          onFocus={() => setShowControls(true)}
          onBlur={() => setShowControls(false)}
        >
          {livestreamVisuallyOffline ? (
            <Box sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              minHeight: isMobile ? 180 : 0,
              width: "100%",
              bgcolor: "rgba(2,6,23,0.94)",
              color: "#cbd5e1",
            }}>
              <Typography variant="body2">
                Klienten er offline — afventer Livestream v2
              </Typography>
            </Box>
          ) : (
            <Box
              ref={videoContainerRef}
              sx={{
                position: "relative",
                width: "100%",
                aspectRatio: livestreamAspectRatio,
                minHeight: { xs: 180, md: "100%" },
                height: { xs: "auto", md: "100%" },
                maxHeight: { xs: 280, md: "none" },
                bgcolor: "#000",
                display: "flex",
                "&:fullscreen": {
                  width: "100vw",
                  height: "100vh",
                  maxHeight: "100vh",
                  aspectRatio: livestreamAspectRatio,
                  background: "#000",
                },
                "&:-webkit-full-screen": {
                  width: "100vw",
                  height: "100vh",
                  maxHeight: "100vh",
                  background: "#000",
                },
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <video
                ref={videoRef}
                id="livestream-video"
                autoPlay
                playsInline
                muted
                onWaiting={handleVideoWaiting}
                onPlaying={handleVideoPlaying}
                onCanPlay={handleVideoCanPlay}
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "contain",
                  background: "#000",
                  display: "block",
                }}
                tabIndex={-1}
                key={effectiveRefreshKey}
              />

              {streamOverlayMeta && (
                <Box
                  sx={{
                    position: "absolute",
                    top: { xs: 8, sm: 12 },
                    left: { xs: 8, sm: 12 },
                    zIndex: 30,
                    maxWidth: { xs: "calc(100% - 16px)", sm: "min(74%, 720px)" },
                    px: { xs: 1.05, sm: 1.25 },
                    py: { xs: 0.75, sm: 0.9 },
                    borderRadius: 2,
                    bgcolor: streamOverlaySx.bg,
                    border: `1px solid ${streamOverlaySx.border}`,
                    color: "#f8fafc",
                    boxShadow: "0 14px 36px rgba(0,0,0,0.36)",
                    backdropFilter: "blur(10px)",
                    pointerEvents: "none",
                    opacity: streamOverlayMeta.persistent || showControls ? 1 : 0.86,
                    transition: "opacity 240ms ease, transform 240ms ease",
                    transform: streamOverlayMeta.persistent || showControls ? "translateY(0)" : "translateY(-2px)",
                  }}
                >
                  <Stack
                    direction="row"
                    spacing={0.9}
                    sx={{
                      alignItems: "flex-start",
                      minWidth: 0
                    }}>
                    <Box
                      sx={{
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        mt: "6px",
                        bgcolor: streamOverlaySx.dot,
                        boxShadow: `0 0 0 5px ${alpha(streamOverlaySx.dot, 0.16)}`,
                        flex: "0 0 auto",
                      }}
                    />
                    <Box sx={{
                      minWidth: 0
                    }}>
                      <Typography
                        variant="caption"
                        sx={{
                          display: "block",
                          fontWeight: 950,
                          lineHeight: 1.15,
                          letterSpacing: "0.01em",
                          color: "#fff",
                        }}
                      >
                        {streamOverlayMeta.title}
                      </Typography>
                      {streamOverlayMeta.detail && (
                        <Typography
                          variant="caption"
                          sx={{
                            display: "block",
                            mt: 0.2,
                            color: "rgba(226,232,240,0.86)",
                            lineHeight: 1.25,
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                        >
                          {streamOverlayMeta.detail}
                        </Typography>
                      )}
                    </Box>
                  </Stack>
                </Box>
              )}

              {!manifestReady && (
                <Box sx={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: "rgba(0,0,0,0.92)",
                  zIndex: 5,
                }}>
                  <CircularProgress size={isMobile ? 24 : 32} sx={{ color: "#fff" }} />
                  <Typography variant="body2" sx={{ color: "#fff", ml: 2 }}>
                    {loadingText}
                  </Typography>
                </Box>
              )}

              {manifestReady && buffering && (
                <Box sx={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  zIndex: 10,
                  background: "rgba(0,0,0,0.45)",
                }}>
                  <CircularProgress size={isMobile ? 20 : 40} sx={{ color: "#fff" }} />
                  <Typography variant="body2" sx={{ color: "#fff", ml: isMobile ? 1 : 2 }}>
                    Buffering …
                  </Typography>
                </Box>
              )}

              {manifestReady && (
                <IconButton
                  onClick={handleFullscreen}
                  aria-label="Fuld skærm"
                  sx={{
                    position: "absolute",
                    bottom: 12,
                    right: 12,
                    bgcolor: alpha("#222", 0.6),
                    color: "#fff",
                    borderRadius: "50%",
                    zIndex: 20,
                    boxShadow: "0 2px 8px rgba(0,0,0,0.19)",
                    opacity: showControls ? 1 : 0,
                    pointerEvents: showControls ? "auto" : "none",
                    transition: "opacity 0.3s",
                    "&:hover": { bgcolor: alpha("#111", 0.85) },
                  }}
                  size={isMobile ? "small" : "medium"}
                  tabIndex={0}
                >
                  <FullscreenIcon sx={{ fontSize: isMobile ? 26 : 32 }} />
                </IconButton>
              )}
            </Box>
          )}
        </Box>

        <Box
          sx={{
            height: { xs: "auto", md: "var(--stream-panel-height)" },
            minHeight: { xs: "auto", md: "var(--stream-panel-height)" },
            maxHeight: { xs: "none", md: "var(--stream-panel-height)" },
            width: "100%",
            maxWidth: "none",
            ml: 0,
            justifySelf: { xs: "stretch", md: "end" },
            alignSelf: "stretch",
            p: { xs: 1.55, sm: 1.95 },
            borderRadius: 2,
            background: "rgba(15,23,42,0.46)",
            border: "1px solid rgba(148,163,184,0.16)",
            display: isSuperadmin || isViewer ? "grid" : "none",
            flexDirection: "column",
            gap: 1.05,
            minWidth: 0,
            overflow: "hidden",
            textAlign: "left",
            gridTemplateRows: { xs: "none", md: "repeat(5, minmax(0, 1fr))" },
          }}
        >
          {[
            {
              label: "Sidste segment",
              value: lastSegmentTimestamp && clientOnline !== false
                ? formatDateTimeWithDay(new Date(lastSegmentTimestamp))
                : "Ikke modtaget",
            },
            { label: "Segmenter", value: `${currentSegNum ?? "-"} / ${lastSegNum ?? "-"}` },
            { label: "Total lag", value: formatLagValue(computedLag), color: manifestReady ? lagStatus.color : "#cbd5e1" },
            { label: "Uploadalder", value: formatLagValue(lastSegmentLag) },
            { label: "Skærm", value: currentDisplayDescription, detail: canManageDisplaySettings ? displayResolutionUiMeta.short : null, detailColor: displayResolutionUiMeta.severity === "error" ? "#f87171" : displayResolutionUiMeta.busy ? "#7dd3fc" : "rgba(203,213,225,0.62)" },
          ].map((item) => (
            <Box
              key={item.label}
              sx={{
                p: { xs: 1.15, sm: 1.25, md: 0.95, lg: 1.05 },
                borderRadius: 2,
                flex: { xs: "0 0 auto", md: "unset" },
                alignSelf: "stretch",
                justifySelf: "stretch",
                width: "100%",
                minHeight: 0,
                overflow: "hidden",
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                textAlign: "left",
                background: "rgba(2,6,23,0.34)",
                border: "1px solid rgba(148,163,184,0.12)",
                minWidth: 0,
              }}
            >
              <Typography
                variant="caption"
                sx={{
                  display: "block",
                  color: "rgba(203,213,225,0.66)",
                  fontWeight: 850,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                  fontSize: { md: 10.5, lg: 11 },
                  lineHeight: 1.05,
                }}
              >
                {item.label}
              </Typography>
              <Typography
                sx={{
                  color: item.color || "#f8fafc",
                  fontWeight: 900,
                  fontSize: { xs: 14, md: 13, lg: 14 },
                  lineHeight: 1.16,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  wordBreak: "break-word",
                }}
              >
                {item.value}
              </Typography>
              {item.detail && (
                <Typography
                  variant="caption"
                  sx={{
                    color: item.detailColor,
                    display: "block",
                    mt: 0.15,
                    lineHeight: 1.1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {item.detail}
                </Typography>
              )}
            </Box>
          ))}
        </Box>
        </Box>
      </Stack>
      <Dialog open={settingsOpen} onClose={() => !settingsSaving && setSettingsOpen(false)} maxWidth="md" fullWidth disableRestoreFocus>
        <DialogTitle>Skærmindstillinger</DialogTitle>
        <DialogContent sx={{ pt: 1 }}>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert
              severity={displayResolutionUiMeta.severity}
              icon={displayResolutionUiMeta.busy || settingsSaving ? <CircularProgress size={16} /> : undefined}
            >
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {settingsSaving ? "Sender skærmhandling…" : displayResolutionWatchingAction === "detect" ? "Auto-detekterer skærm…" : displayResolutionUiMeta.title}
              </Typography>
              <Typography variant="body2">
                {settingsSaving ? "Sender handlingen til backend." : displayResolutionWatchingAction === "detect" ? "Dialogen henter automatisk klientens aktuelle skærmstørrelse. Vælg derefter den opløsning, der skal gemmes eller anvendes." : displayResolutionUiMeta.detail}
              </Typography>
              <Typography variant="caption" component="div" sx={{ mt: 0.5 }}>
                Aktuel rapporteret skærm: {currentDisplayReport}
              </Typography>
              {client?.display_resolution_error && displayResolutionStatusNorm === "error" && (
                <Typography variant="caption" component="div" sx={{ mt: 0.5 }}>
                  Fejl: {client.display_resolution_error}
                </Typography>
              )}
            </Alert>

            {displayResolutionOptions.some((option) => option.source === "client") ? (
              <Alert severity="success">
                Der vises kun opløsninger, som klienten selv har rapporteret som tilgængelige.
              </Alert>
            ) : (
              <Alert severity="warning">
                Klienten har endnu ikke sendt en liste over tilgængelige skærmindstillinger. Brug “Auto-detekter” eller vent på næste klientstatus.
              </Alert>
            )}

            <TextField
              select
              label="Vælg opløsning"
              value={settingsForm.preset}
              onChange={handlePresetChange}
              fullWidth
              size="small"
              helperText={
                displayResolutionOptions.some((option) => option.source === "client")
                  ? "Listen kommer fra klientens rapporterede skærm-modes."
                  : "Klienten har endnu ikke rapporteret en mode-liste — fallback vises."
              }
            >
              {displayResolutionOptions.map((preset) => (
                <MenuItem key={preset.value} value={preset.value}>{preset.label}</MenuItem>
              ))}
            </TextField>

            {client?.display_detected_updated_at && (
              <Typography variant="caption" sx={{
                color: "text.secondary"
              }}>
                Tilgængelige skærmindstillinger opdateret: {formatDateTimeWithDay(client.display_detected_updated_at)}
              </Typography>
            )}

            {settingsForm.preset !== "auto" && (
              <Grid container spacing={2}>
                <Grid
                  size={{
                    xs: 12,
                    sm: 6
                  }}>
                  <TextField
                    label="Bredde"
                    type="number"
                    size="small"
                    fullWidth
                    value={settingsForm.width}
                    onChange={(e) => {
                      setSettingsTouched(true);
                      setSettingsForm((prev) => ({ ...prev, width: e.target.value }));
                    }}
                    disabled={settingsForm.preset !== "custom"}
                    slotProps={{
                      htmlInput: { min: 320, max: 8192 }
                    }}
                  />
                </Grid>
                <Grid
                  size={{
                    xs: 12,
                    sm: 6
                  }}>
                  <TextField
                    label="Højde"
                    type="number"
                    size="small"
                    fullWidth
                    value={settingsForm.height}
                    onChange={(e) => {
                      setSettingsTouched(true);
                      setSettingsForm((prev) => ({ ...prev, height: e.target.value }));
                    }}
                    disabled={settingsForm.preset !== "custom"}
                    slotProps={{
                      htmlInput: { min: 320, max: 8192 }
                    }}
                  />
                </Grid>
              </Grid>
            )}

            {settingsForm.preset !== "auto" && (
              <TextField
                label="Refresh rate (valgfri)"
                type="number"
                size="small"
                fullWidth
                value={settingsForm.refreshRate}
                onChange={(e) => {
                  setSettingsTouched(true);
                  setSettingsForm((prev) => ({ ...prev, refreshRate: e.target.value }));
                }}
                helperText="Lad feltet være tomt for at bruge skærmens standard-refresh rate"
                slotProps={{
                  htmlInput: { min: 1, max: 240, step: "0.01" }
                }}
              />
            )}

            {!selectedDisplayIsAuto && selectedDisplayAlreadyActive && (
              <Alert severity="success">
                Den valgte opløsning ({selectedResolutionDescription}) matcher den aktuelle skærm. Der er ingen ændringer at gemme.
              </Alert>
            )}

            {selectedDisplayHasActualChange && (
              <Alert severity="warning">
                Tryk “Gem og anvend” for at ændre klientens fysiske skærm til {selectedResolutionDescription}.
              </Alert>
            )}

            {settingsError && <Alert severity="error">{settingsError}</Alert>}
            {settingsMessage && <Alert severity="info">{settingsMessage}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSettingsOpen(false)} disabled={settingsSaving}>
            {displayResolutionBusy ? "Luk — processen fortsætter" : "Luk"}
          </Button>
          <Button onClick={handleSaveLivestreamSettings} variant="contained" disabled={displaySaveButtonDisabled}>
            {settingsSaving ? <CircularProgress size={18} color="inherit" sx={{ mr: 1 }} /> : null}
            {displaySaveButtonLabel}
          </Button>
        </DialogActions>
      </Dialog>
      <style>{`
        @keyframes pulsate {
          0%   { transform: scale(1);    opacity: 1;   background: #43a047; }
          50%  { transform: scale(1.25); opacity: 0.5; background: #43a047; }
          100% { transform: scale(1);    opacity: 1;   background: #43a047; }
        }
      `}</style>
    </Card>
  );
}
