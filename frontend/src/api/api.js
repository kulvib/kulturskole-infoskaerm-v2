import { API_ORIGIN, WS_API_ORIGIN, buildApiUrl } from "../config/apiConfig";
import { buildBrowserWsProtocols, buildBrowserWsUrl } from "./browserWebSocket";
import { createApiError, formatApiError, normalizeApiError } from "./apiError";

/*
  api.js

  Alle backend-kald samlet ét sted.

  FIX: getMarkedDays(season, client_id, startDate, endDate)
    — parametrene var byttet om i ClientDetailsPageWrapper (id, season)
    — signaturen er nu tydelig dokumenteret med JSDoc
    — bruges korrekt i ClientCalendarDialog og ClientDetailsPageWrapper

  Canonical control actions:
    — reboot/shutdown → dedicated System command endpoint
    — start/stop/reset/sleep/wakeup → dedicated Display command endpoint
*/

// Worklog/Flow-princip: tom VITE_API_URL betyder same-origin.
// Frontend kalder /api/* på display.planiq.dk, og Render rewrites proxyer
// requesten til backend. Det gør refresh-cookie first-party/same-origin i browseren.
export const apiUrl = API_ORIGIN;

const authApiBase = buildApiUrl("/auth");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let accessTokenInMemory = null;
let sessionExpiresAtInMemory = null;
let refreshPromise = null;
let bootRefreshPromise = null;
let refreshBlockedUntil = 0;
let adminTerminalStepUpInMemory = null;
const nativeFetch = globalThis.fetch.bind(globalThis);
const NETWORK_ERROR_MESSAGE = "Netværksfejl – tjek din internetforbindelse og prøv igen.";

function buildNetworkError(err) {
  if (err?.name === "AbortError") return err;
  return normalizeApiError(err, NETWORK_ERROR_MESSAGE);
}

async function fetchWithFriendlyErrors(input, init) {
  try {
    return await nativeFetch(input, init);
  } catch (err) {
    throw buildNetworkError(err);
  }
}

export function getAuthToken() {
  return accessTokenInMemory || "";
}

export function setAuthToken(token) {
  accessTokenInMemory = token || null;
}

export function clearAuthToken() {
  accessTokenInMemory = null;
  sessionExpiresAtInMemory = null;
  adminTerminalStepUpInMemory = null;
}

export function setAdminTerminalStepUp(token, expiresAt) {
  const normalizedToken = String(token || "");
  const expiryMs = Date.parse(String(expiresAt || ""));
  if (!normalizedToken || !Number.isFinite(expiryMs)) {
    adminTerminalStepUpInMemory = null;
    return;
  }
  adminTerminalStepUpInMemory = { token: normalizedToken, expiresAtMs: expiryMs };
}

export function clearAdminTerminalStepUp() {
  adminTerminalStepUpInMemory = null;
}

export function getAdminTerminalStepUpToken() {
  const value = adminTerminalStepUpInMemory;
  if (!value?.token || !Number.isFinite(value?.expiresAtMs) || value.expiresAtMs <= Date.now() + 5000) {
    adminTerminalStepUpInMemory = null;
    return "";
  }
  return value.token;
}

export function hasRecentAdminTerminalStepUp() {
  return Boolean(getAdminTerminalStepUpToken());
}

export function setSessionExpiresAt(value) {
  sessionExpiresAtInMemory = value || null;
}

export function getSessionExpiresAt() {
  return sessionExpiresAtInMemory;
}

export function authHeaders(extra = {}) {
  const token = getAuthToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : { ...extra };
}

function isPublicOrSessionEndpoint(url = "") {
  const value = String(url);
  return (
    value.includes("/api/auth/token") ||
    value.includes("/api/auth/refresh") ||
    value.includes("/api/auth/logout") ||
    value.includes("/api/users/forgot-password") ||
    value.includes("/api/users/reset-password") ||
    value.endsWith("/health") ||
    value.includes("/health/db")
  );
}

async function refreshAccessToken() {
  if (refreshPromise) return refreshPromise;
  const now = Date.now();
  if (refreshBlockedUntil > now) {
    const err = new Error("Sessionen kunne ikke fornyes endnu.");
    err.status = 429;
    err.retryAfterSeconds = Math.ceil((refreshBlockedUntil - now) / 1000);
    throw normalizeApiError(err, err.message);
  }

  refreshPromise = fetchWithFriendlyErrors(`${authApiBase}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
  })
    .then(async (res) => {
      if (!res.ok) {
        const err = await buildApiErrorFromResponse(res, "Sessionen er udløbet");
        if (res.status === 429) {
          const waitSeconds = Number.isFinite(err.retryAfterSeconds) ? err.retryAfterSeconds : 30;
          refreshBlockedUntil = Date.now() + waitSeconds * 1000;
        }
        throw err;
      }
      refreshBlockedUntil = 0;
      const data = await readJsonResponse(res, "Uventet svar fra session-fornyelse");
      setAuthToken(data?.access_token || "");
      setSessionExpiresAt(data?.session_expires_at || null);
      return data;
    })
    .catch((err) => {
      if (err?.status !== 429) clearAuthToken();
      throw err;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

export async function performBootRefresh() {
  if (getAuthToken()) return { session_expires_at: getSessionExpiresAt() };
  if (bootRefreshPromise) return bootRefreshPromise;

  bootRefreshPromise = refreshAccessToken()
    .then((data) => data || true)
    .catch(() => false)
    .finally(() => {
      bootRefreshPromise = null;
    });

  return bootRefreshPromise;
}

// Bruges af sessiondialogen til en eksplicit servervalidering. Funktionen
// deler samme single-flight refresh som almindelige 401-retries.
export function refreshSession() {
  return refreshAccessToken();
}

async function apiFetch(input, init = {}) {
  const url = typeof input === "string" ? input : input?.url || "";
  const { _retried, ...fetchInit } = init;
  const headers = authHeaders(fetchInit.headers || {});
  const first = await fetchWithFriendlyErrors(input, {
    ...fetchInit,
    headers,
    credentials: fetchInit.credentials || "include",
  });

  if (first.status !== 401 || isPublicOrSessionEndpoint(url) || _retried) {
    return first;
  }

  try {
    await refreshAccessToken();
  } catch {
    clearAuthToken();
    localStorage.removeItem("user");
    window.location.href = "/login";
    return first;
  }

  return fetchWithFriendlyErrors(input, {
    ...fetchInit,
    headers: authHeaders(fetchInit.headers || {}),
    credentials: fetchInit.credentials || "include",
  });
}

function handle401() {
  clearAuthToken();
  localStorage.removeItem("user");
  window.location.href = "/login";
}

export function getWsApiUrl() {
  if (WS_API_ORIGIN) return WS_API_ORIGIN;
  if (apiUrl.startsWith("https://")) return `wss://${apiUrl.slice("https://".length)}`;
  if (apiUrl.startsWith("http://")) return `ws://${apiUrl.slice("http://".length)}`;
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin.replace(/^http/, "ws");
  }
  return apiUrl;
}

function getBrowserWsUrl(path, params = null) {
  return buildBrowserWsUrl(getWsApiUrl(), path, params);
}

export async function createBrowserWsTicket(clientId, capability) {
  const numericClientId = Number(clientId);
  if (!Number.isInteger(numericClientId) || numericClientId < 1) {
    throw new Error("Klient-id mangler til WebSocket-forbindelsen.");
  }

  const allowedCapabilities = new Set(["remote_desktop"]);
  if (!allowedCapabilities.has(capability)) {
    throw new Error("Ukendt WebSocket-funktion.");
  }

  const res = await apiFetch(buildApiUrl("/websocket-tickets/browser"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: numericClientId, capability }),
  });
  if (!res.ok) {
    throw await buildApiErrorFromResponse(res, "Kunne ikke oprette en sikker WebSocket-forbindelse");
  }

  const data = await readJsonResponse(res, "Uventet svar fra WebSocket-ticket-endpointet");
  return {
    ticket: String(data?.ticket || ""),
    subprotocol: String(data?.subprotocol || ""),
    expiresAt: data?.expires_at || null,
  };
}

export async function createTerminalBrowserWsTicket(clientId, mode = "user") {
  const numericClientId = Number(clientId);
  if (!Number.isInteger(numericClientId) || numericClientId < 1) {
    throw new Error("Klient-id mangler til Terminal WebSocket-forbindelsen.");
  }

  const normalizedMode = mode === "admin" ? "admin" : mode === "user" ? "user" : null;
  if (!normalizedMode) {
    throw new Error("Ukendt Terminal-tilstand.");
  }

  const res = await apiFetch(buildApiUrl("/terminal/browser-ticket"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: numericClientId, mode: normalizedMode }),
  });
  if (!res.ok) {
    throw await buildApiErrorFromResponse(res, "Kunne ikke oprette en sikker Terminal WebSocket-forbindelse");
  }

  const data = await readJsonResponse(res, "Uventet svar fra Terminal WebSocket-ticket-endpointet");
  return {
    ticket: String(data?.ticket || ""),
    subprotocol: String(data?.subprotocol || ""),
    expiresAt: data?.expires_at || null,
  };
}

export function getBrowserWsProtocols(ticketResponse) {
  return buildBrowserWsProtocols(ticketResponse?.ticket, ticketResponse?.subprotocol);
}

export function getTerminalBrowserWsUrl(clientId, mode = "user") {
  const params = new URLSearchParams();
  params.set("mode", mode === "admin" ? "admin" : "user");
  return getBrowserWsUrl(`/api/terminal/browser/${encodeURIComponent(clientId)}/ws`, params);
}

export function getRemoteDesktopBrowserWsUrl(clientId) {
  return getBrowserWsUrl(`/api/remote-desktop/browser/${encodeURIComponent(clientId)}/ws`);
}

function normalizeChromeStatusPayload(data = {}) {
  const normalized = { ...(data || {}) };

  const latestStepFromArray = Array.isArray(normalized.steps) && normalized.steps.length > 0
    ? normalized.steps[normalized.steps.length - 1]
    : null;

  const stepValue =
    normalized?.step?.step ??
    normalized?.chrome_step ??
    normalized?.last_chrome_step ??
    latestStepFromArray?.step ??
    null;

  const stepTimestamp =
    normalized?.step?.timestamp ??
    normalized?.chrome_step_timestamp ??
    normalized?.chrome_last_updated ??
    latestStepFromArray?.timestamp ??
    null;

  normalized.chrome_step = stepValue ?? null;
  normalized.last_chrome_step = stepValue ?? null;
  normalized.step = stepValue
    ? { step: stepValue, timestamp: stepTimestamp }
    : null;

  if (typeof normalized.chrome_running !== "boolean" && typeof normalized.chromeRunning === "boolean") {
    normalized.chrome_running = normalized.chromeRunning;
  }
  if (typeof normalized.chromeRunning !== "boolean" && typeof normalized.chrome_running === "boolean") {
    normalized.chromeRunning = normalized.chrome_running;
  }

  return normalized;
}

export async function readJsonResponse(res, fallback = "Uventet svar fra serveren") {
  const contentType = res?.headers?.get?.("content-type") || "";
  const text = await res.text();

  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch {
    const looksLikeHtml = /^\s*(?:<!doctype\s+html|<html|<head|<body)/i.test(text);
    if (looksLikeHtml || contentType.includes("text/html")) {
      throw new Error(
        "Backend svarer med HTML i stedet for JSON. Tjek Render rewrite/proxy for /api/* og at VITE_API_URL ikke peger på frontend."
      );
    }
    throw new Error(fallback);
  }
}

async function readJsonOrDefault(res, fallbackValue = {}) {
  try {
    const data = await readJsonResponse(res);
    return data ?? fallbackValue;
  } catch {
    return fallbackValue;
  }
}

async function buildApiErrorFromResponse(res, fallback) {
  let data = null;
  try {
    data = await readJsonResponse(res, fallback);
  } catch {
    // HTML eller ugyldigt svar må ikke overskygge status/request-id.
  }
  return createApiError({ response: res, body: data, fallback });
}

async function extractError(res, fallback) {
  return formatApiError(await buildApiErrorFromResponse(res, fallback), fallback);
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export async function login(username, password) {
  const res = await apiFetch(`${authApiBase}/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username, password }),
    credentials: "include",
  });
  if (!res.ok) {
    throw await buildApiErrorFromResponse(res, "Forkert brugernavn eller kodeord");
  }
  const data = await readJsonResponse(res, "Uventet svar fra login-endpoint");
  setAuthToken(data?.access_token || "");
  setSessionExpiresAt(data?.session_expires_at || null);
  return data;
}

export async function logout() {
  try {
    await apiFetch(`${authApiBase}/logout`, {
      method: "POST",
      headers: authHeaders(),
      credentials: "include",
    });
  } finally {
    clearAuthToken();
  }
}


export async function forgotPassword(identifier) {
  const res = await apiFetch(`${apiUrl}/api/users/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ identifier }),
  });
  if (!res.ok) throw await buildApiErrorFromResponse(res, "Kunne ikke sende nulstillingslink");
  return readJsonResponse(res);
}

export async function resetPassword(token, password) {
  const res = await apiFetch(`${apiUrl}/api/users/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ token, password }),
  });
  if (!res.ok) throw await buildApiErrorFromResponse(res, "Kunne ikke nulstille adgangskode");
  return readJsonResponse(res);
}

// ---------------------------------------------------------------------------
// Klienter
// ---------------------------------------------------------------------------

export async function getClients() {
  const res = await apiFetch(`${apiUrl}/api/clients/`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente klienter"));
  return readJsonResponse(res);
}

export async function getMyClients() {
  const res = await apiFetch(`${apiUrl}/api/clients/me`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente klienter (me)"));
  return readJsonResponse(res);
}


export async function getClient(id) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente klient"));
  return readJsonResponse(res);
}

export async function getClientPresence(id) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/presence`, {
    headers: authHeaders({ Accept: "application/json" }),
    credentials: "include",
    cache: "no-store",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente klient-presence"));
  return readJsonResponse(res, "Kunne ikke læse klient-presence");
}

/**
 * Hent browser/runtime-status. Global client-liveness hentes separat fra
 * /presence og må aldrig rekonstrueres fra chrome-status eller Client-felter.
 */
export async function getChromeStatus(id, { fallbackToClient = false } = {}) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/chrome-status`, {
    headers: authHeaders({ Accept: "application/json" }),
    credentials: "include",
  });

  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }

  if (!res.ok) {
    if (fallbackToClient) {
      const full = await getClient(id);
      return normalizeChromeStatusPayload({
        chrome_status: full.chrome_status ?? null,
        chrome_color: full.chrome_color ?? null,
        chrome_last_updated: full.chrome_last_updated ?? null,
        chrome_step: full.chrome_step ?? null,
        state: full.state ?? null,
        pending_chrome_action: full.pending_chrome_action ?? "none",
        pending_chrome_action_source: full.pending_chrome_action_source ?? null,
        livestream_desired_state: full.livestream_desired_state ?? "stopped",
        livestream_stop_reason: full.livestream_stop_reason ?? null,
        pending_reboot: full.pending_reboot ?? false,
        pending_shutdown: full.pending_shutdown ?? false,
        pending_os_update: full.pending_os_update ?? false,
        ubuntu_updates_available: full.ubuntu_updates_available ?? 0,
        service_ubuntu_update_status: full.service_ubuntu_update_status ?? null,
        uptime: full.uptime ?? null,
        chrome_running: full.chrome_running ?? full.chromeRunning ?? null,
        network_status: full.network_status ?? null,
        network_status_message: full.network_status_message ?? null,
        network_status_color: full.network_status_color ?? null,
        network_has_connection: full.network_has_connection ?? null,
        diagnostics_updated_at: full.diagnostics_updated_at ?? null,
        active_network_type: full.active_network_type ?? null,
        active_network_interface: full.active_network_interface ?? null,
        active_network_ip: full.active_network_ip ?? null,
        active_network_mac: full.active_network_mac ?? null,
        wifi_ip_address: full.wifi_ip_address ?? null,
        wifi_mac_address: full.wifi_mac_address ?? null,
        lan_ip_address: full.lan_ip_address ?? null,
        lan_mac_address: full.lan_mac_address ?? null,
      });
    }
    throw new Error(await extractError(res, "Kunne ikke hente chrome status"));
  }

  const json = normalizeChromeStatusPayload(await readJsonResponse(res, "Kunne ikke læse chrome status"));

  if (
    fallbackToClient &&
    (json?.uptime == null ||
      json?.pending_os_update == null ||
      json?.service_ubuntu_update_status == null)
  ) {
    try {
      const full = await getClient(id);
      return normalizeChromeStatusPayload({
        ...json,
        uptime: json.uptime ?? full.uptime ?? null,
        pending_os_update: json.pending_os_update ?? full.pending_os_update ?? false,
        ubuntu_updates_available: json.ubuntu_updates_available ?? full.ubuntu_updates_available ?? 0,
        service_ubuntu_update_status: json.service_ubuntu_update_status ?? full.service_ubuntu_update_status ?? null,
        livestream_desired_state: json.livestream_desired_state !== undefined
          ? (json.livestream_desired_state ?? "stopped")
          : (full.livestream_desired_state ?? "stopped"),
        livestream_stop_reason: json.livestream_stop_reason !== undefined
          ? json.livestream_stop_reason
          : (full.livestream_stop_reason ?? null),
        network_status: json.network_status ?? full.network_status ?? null,
        network_status_message: json.network_status_message ?? full.network_status_message ?? null,
        network_status_color: json.network_status_color ?? full.network_status_color ?? null,
        network_has_connection: json.network_has_connection ?? full.network_has_connection ?? null,
        diagnostics_updated_at: json.diagnostics_updated_at ?? full.diagnostics_updated_at ?? null,
        active_network_type: json.active_network_type ?? full.active_network_type ?? null,
        active_network_interface: json.active_network_interface ?? full.active_network_interface ?? null,
        active_network_ip: json.active_network_ip ?? full.active_network_ip ?? null,
        active_network_mac: json.active_network_mac ?? full.active_network_mac ?? null,
        wifi_ip_address: json.wifi_ip_address ?? full.wifi_ip_address ?? null,
        wifi_mac_address: json.wifi_mac_address ?? full.wifi_mac_address ?? null,
        lan_ip_address: json.lan_ip_address ?? full.lan_ip_address ?? null,
        lan_mac_address: json.lan_mac_address ?? full.lan_mac_address ?? null,
      });
    } catch {
      // Chrome/runtime endpointet er stadig autoritativt for de felter det sendte.
    }
  }

  return json;
}

export async function updateClient(id, updates) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/update`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(updates),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke opdatere klient"));
  return readJsonResponse(res);
}

export async function getClientLocalManagement(id) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(id)}/local-management`, {
    headers: authHeaders({ Accept: "application/json" }),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente lokal klientstyring"));
  return readJsonResponse(res);
}

export async function requestCfadminPasswordChange(id, password) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(id)}/local-management/cfadmin-password`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ password }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke sende cfadmin-adgangskodeændring"));
  return readJsonResponse(res);
}

export async function requestLocalHostnameChange(id, name) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(id)}/local-management/hostname`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ name }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke sende lokalt klientnavn"));
  return readJsonResponse(res);
}

export async function approveClient(id, organization_id) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/approve`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: organization_id ? JSON.stringify({ organization_id }) : undefined,
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke godkende klient"));
  return readJsonResponse(res);
}

export async function getDeletedClients() {
  const res = await apiFetch(`${apiUrl}/api/clients/deleted`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente papirkurv"));
  return readJsonResponse(res);
}

export async function removeClient(id, reason = "") {
  const body = reason ? JSON.stringify({ reason }) : undefined;
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/remove`, {
    method: "DELETE",
    headers: authHeaders(reason ? { "Content-Type": "application/json" } : undefined),
    credentials: "include",
    body,
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke flytte klient til papirkurv"));
  return readJsonOrDefault(res, {});
}

export async function restoreClient(id) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/restore`, {
    method: "POST",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke gendanne klient"));
  return readJsonResponse(res);
}

export async function purgeClient(id) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/purge`, {
    method: "DELETE",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke slette klient permanent"));
  return readJsonOrDefault(res, {});
}

export async function pushKioskUrl(id, url) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/kiosk_url`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ kiosk_url: url }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke opdatere kiosk webadresse"));
  return readJsonResponse(res);
}

/**
 * Udfør en handling på en klient.
 *
 * Gyldige actions:
 *   "start"            → pending_chrome_action: "start"
 *   "stop"             → pending_chrome_action: "stop"
 *   "restart"          → canonical System command: reboot
 *   "reboot"           → canonical System command: reboot
 *   "shutdown"         → canonical System command: shutdown
 *   "sleep"            → action: "sleep"
 *   "wakeup"           → action: "wakeup"
 *   "reset_browser"    → pending_chrome_action: "reset_browser"
 */
export async function clientAction(id, action, source = "actionbutton") {
  // Kiosk-/display-handlinger sendes via det dedikerede command-endpoint.
  // Det giver backend en tydelig source og undgår at /update genbruger gamle
  // pending_chrome_action_source værdier.
  const commandActionMap = {
    start: "start",
    stop: "stop",
    sleep: "sleep",
    wakeup: "wakeup",
    reset_browser: "reset_browser",
  };

  if (action === "restart" || action === "reboot" || action === "shutdown") {
    const systemAction = action === "restart" ? "reboot" : action;
    const res = await apiFetch(`${apiUrl}/api/clients/${id}/system-command`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({ action: systemAction, source }),
    });
    if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
    if (!res.ok) throw new Error(await extractError(res, "Kunne ikke udføre System-handling"));
    return readJsonResponse(res);
  }

  const mappedAction = commandActionMap[action];
  if (!mappedAction) {
    throw new Error("Ukendt action: " + action);
  }

  const commandEndpoint = mappedAction.startsWith("livestream_")
    ? "livestream-command"
    : "chrome-command";
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/${commandEndpoint}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({
      action: mappedAction,
      source,
    }),
  });

  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke udføre handling"));
  return readJsonResponse(res);
}

export async function setClientState(id, state) {
  const res = await apiFetch(`${apiUrl}/api/clients/${id}/state`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ state }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke sætte klientens tilstand"));
  return readJsonResponse(res);
}

export function openRemoteDesktop(id) {
  window.open(`/remote-desktop/${id}`, "_blank", "noopener");
}

// ---------------------------------------------------------------------------
// Kalender
// ---------------------------------------------------------------------------

export async function saveMarkedDays(payload) {
  const res = await apiFetch(`${apiUrl}/api/calendar/marked-days`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke gemme kalender"));
  return readJsonResponse(res);
}

/**
 * Hent markerede dage for en klient i en sæson.
 *
 * FIX: Parametrene er (season, client_id) — IKKE (client_id, season).
 * ClientDetailsPageWrapper kaldte tidligere getMarkedDays(id, season)
 * hvilket gav tomme resultater. Korrekt kald: getMarkedDays(season, id).
 *
 * @param {string|number} season      - Sæson ID
 * @param {string|number} client_id   - Klient ID
 * @param {string}        [startDate] - YYYY-MM-DD
 * @param {string}        [endDate]   - YYYY-MM-DD
 */
export async function getMarkedDays(season, client_id, startDate, endDate) {
  const params = new URLSearchParams({
    season: String(season),
    client_id: String(client_id),
  });
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);

  const res = await apiFetch(
    `${apiUrl}/api/calendar/marked-days?${params.toString()}`,
    { headers: authHeaders(), credentials: "include" }
  );
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) return { markedDays: {} };
  return readJsonResponse(res);
}

export async function getCurrentSeason() {
  const res = await apiFetch(`${apiUrl}/api/calendar/season`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error("Kunne ikke hente aktuel sæson");
  return readJsonResponse(res);
}

export async function getCalendarSeasons() {
  const res = await apiFetch(`${apiUrl}/api/calendar/seasons`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente sæsoner"));
  return readJsonResponse(res);
}

export async function getSeasonReadiness(organizationId, season) {
  const params = new URLSearchParams({
    organization_id: String(organizationId),
    season: String(season),
  });
  const res = await apiFetch(
    `${apiUrl}/api/calendar/seasons/readiness?${params.toString()}`,
    { headers: authHeaders(), credentials: "include" },
  );
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) {
    throw new Error(await extractError(res, "Kunne ikke kontrollere sæsonens klargøring"));
  }
  return readJsonResponse(res);
}

// ---------------------------------------------------------------------------
// Organisations
// ---------------------------------------------------------------------------
//
// Backend eksponerer /api/organizations og bruger organization_id hele vejen.

export async function getOrganizations() {
  const res = await apiFetch(`${apiUrl}/api/organizations/`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente organisationer"));
  return readJsonResponse(res);
}

export async function addOrganization(name) {
  const res = await apiFetch(`${apiUrl}/api/organizations/`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ name }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke tilføje organisation"));
  return readJsonResponse(res);
}

export async function getOrganizationTimes(organizationId, season) {
  const url = season
    ? `${apiUrl}/api/organizations/${organizationId}/season-times/${encodeURIComponent(season)}`
    : `${apiUrl}/api/organizations/${organizationId}/times`;
  const res = await apiFetch(url, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente organisationstider"));
  return readJsonResponse(res);
}

export async function updateOrganizationTimes(organizationId, season, updates) {
  const res = await apiFetch(
    `${apiUrl}/api/organizations/${organizationId}/season-times/${encodeURIComponent(season)}`,
    {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(updates),
    }
  );
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke opdatere organisationstider"));
  return readJsonResponse(res);
}

export async function applyOrganizationSeasonTimes(organizationId, season, updates) {
  const res = await apiFetch(
    `${apiUrl}/api/organizations/${organizationId}/apply-season-times/${encodeURIComponent(season)}`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(updates),
    }
  );
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) {
    throw new Error(
      await extractError(res, "Kunne ikke anvende organisationens sæsontider på klienter")
    );
  }
  return readJsonResponse(res);
}

export async function replaceOrganizationSeasonCalendars(organizationId, season, updates) {
  const res = await apiFetch(
    `${apiUrl}/api/organizations/${organizationId}/replace-season-calendars/${encodeURIComponent(season)}`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(updates),
    }
  );
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) {
    throw new Error(
      await extractError(res, "Kunne ikke overskrive organisationens klientkalendere")
    );
  }
  return readJsonResponse(res);
}

export async function getOrganizationSeasonSummary() {
  const res = await apiFetch(`${apiUrl}/api/organizations/season-summary`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) {
    throw new Error(await extractError(res, "Kunne ikke hente organisations-/sæsonoversigt"));
  }
  return readJsonResponse(res);
}

export async function getOrganizationClients(organizationId) {
  const res = await apiFetch(`${apiUrl}/api/organizations/${organizationId}/clients/`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) {
    throw new Error(
      await extractError(res, "Kunne ikke hente klienter for organisation")
    );
  }
  return readJsonResponse(res);
}


export async function getOrganizationLogoBlob(organizationId) {
  const res = await apiFetch(`${apiUrl}/api/organizations/${organizationId}/logo`, {
    headers: authHeaders(),
    credentials: "include",
    cache: "no-store",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente organisationslogo"));
  return res.blob();
}

export async function uploadOrganizationLogo(organizationId, file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await apiFetch(`${apiUrl}/api/organizations/${organizationId}/logo`, {
    method: "PUT",
    headers: authHeaders(),
    credentials: "include",
    body: formData,
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke uploade organisationslogo"));
  return readJsonResponse(res);
}

export async function deleteOrganizationLogo(organizationId) {
  const res = await apiFetch(`${apiUrl}/api/organizations/${organizationId}/logo`, {
    method: "DELETE",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke slette organisationslogo"));
  return readJsonResponse(res);
}

export async function deleteOrganization(id) {
  const res = await apiFetch(`${apiUrl}/api/organizations/${id}/`, {
    method: "DELETE",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke slette organisation"));
}

export async function updateOrganizationName(id, name) {
  const res = await apiFetch(`${apiUrl}/api/organizations/${id}/`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ name }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) {
    throw new Error(await extractError(res, "Kunne ikke opdatere organisationsnavn"));
  }
  return readJsonResponse(res);
}

export async function changeClientOrganization(id, {
  organization_id,
  season = null,
  apply_organization_standard_times = true,
  preserve_manual_times = true,
} = {}) {
  const payload = {
    organization_id,
    apply_organization_standard_times,
    preserve_manual_times,
  };
  if (season) payload.season = season;

  const res = await apiFetch(`${apiUrl}/api/clients/${id}/change-organization`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke skifte organisation"));
  return readJsonResponse(res);
}


// ---------------------------------------------------------------------------
// Brugere
// ---------------------------------------------------------------------------

export async function getUsers() {
  const res = await apiFetch(`${apiUrl}/api/users/`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente brugere"));
  return readJsonResponse(res);
}

export async function createUser(userData) {
  const res = await apiFetch(`${apiUrl}/api/users/`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(userData),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke oprette bruger"));
  return readJsonResponse(res);
}

export async function sendUserPasswordResetLink(id) {
  const res = await apiFetch(`${apiUrl}/api/users/${id}/reset-password`, {
    method: "POST",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw await buildApiErrorFromResponse(res, "Kunne ikke sende nulstillingslink");
  return readJsonResponse(res);
}

export async function assignTemporaryPassword(id, temporaryPassword) {
  const res = await apiFetch(`${apiUrl}/api/users/${id}/temporary-password`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ temporary_password: temporaryPassword }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke tildele midlertidigt password"));
  return readJsonResponse(res);
}

export async function updateUser(id, updates) {
  const res = await apiFetch(`${apiUrl}/api/users/${id}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(updates),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke opdatere bruger"));
  return readJsonResponse(res);
}

export async function deleteUser(id) {
  const res = await apiFetch(`${apiUrl}/api/users/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke slette bruger"));
}

// ---------------------------------------------------------------------------
// OS opdatering
// ---------------------------------------------------------------------------

export async function requestOsUpdate(clientId) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(clientId)}/os-update`, {
    method: "POST",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok)
    throw new Error(await extractError(res, "Kunne ikke anmode om OS opdatering"));
  return readJsonResponse(res);
}

// ---------------------------------------------------------------------------
// ClientFlow selfupdate
// ---------------------------------------------------------------------------

export async function getClientflowReleases() {
  const res = await apiFetch(`${apiUrl}/api/clientflow/releases`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente ClientFlow-versioner"));
  return readJsonResponse(res);
}

export async function getClientflowDeployments(clientId) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(clientId)}/clientflow-deployments`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente ClientFlow-deployments"));
  return readJsonResponse(res);
}

export async function getActiveClientflowDeployment(clientId) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(clientId)}/clientflow-deployments/active`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke hente aktiv ClientFlow-deployment"));
  return readJsonResponse(res);
}

export async function requestClientflowDeployment(clientId, options = {}) {
  const targetVersion = String(options.targetVersion || "").trim();
  if (!targetVersion || targetVersion.toLowerCase() === "latest") {
    throw new Error("ClientFlow-deployment kræver en konkret katalogversion");
  }
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(clientId)}/clientflow-deployments`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({
      target_version: targetVersion,
      confirm_downgrade: options.confirmDowngrade === true,
      reason: options.reason || null,
      pre_first_activation_repair: options.preFirstActivationRepair === true,
    }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke oprette ClientFlow-deployment"));
  return readJsonResponse(res);
}

export async function cancelClientflowDeployment(deploymentId, reason = null) {
  const res = await apiFetch(`${apiUrl}/api/clientflow-deployments/${encodeURIComponent(deploymentId)}/cancel`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ reason: reason || null }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok) throw new Error(await extractError(res, "Kunne ikke annullere ClientFlow-deployment"));
  return readJsonResponse(res);
}

// ---------------------------------------------------------------------------
// Installationskoder / Enrollment tokens
// ---------------------------------------------------------------------------

export async function createEnrollmentToken({ expires_in_hours = 72, note = null } = {}) {
  const res = await apiFetch(`${apiUrl}/api/admin/enrollment-tokens`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    credentials: "include",
    body: JSON.stringify({ expires_in_hours, note }),
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok)
    throw new Error(await extractError(res, "Kunne ikke oprette installationskode"));
  return readJsonResponse(res);
}

export async function getEnrollmentTokens({ include_history = false } = {}) {
  const params = new URLSearchParams();
  if (include_history) params.set("include_history", "true");
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await apiFetch(`${apiUrl}/api/admin/enrollment-tokens${suffix}`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok)
    throw new Error(await extractError(res, "Kunne ikke hente installationskoder"));
  return readJsonResponse(res);
}

export async function revokeEnrollmentToken(id) {
  const res = await apiFetch(`${apiUrl}/api/admin/enrollment-tokens/${encodeURIComponent(id)}/revoke`, {
    method: "POST",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok)
    throw new Error(await extractError(res, "Kunne ikke tilbagekalde installationskode"));
  return readJsonResponse(res);
}

// ---------------------------------------------------------------------------
// Client-secret administration for existing clients
// ---------------------------------------------------------------------------

export async function getClientSecretStatus(clientId) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(clientId)}/client-secret/status`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok)
    throw new Error(await extractError(res, "Kunne ikke hente client-secret status"));
  return readJsonResponse(res);
}

export async function rotateClientSecret(clientId) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(clientId)}/client-secret/rotate`, {
    method: "POST",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok)
    throw new Error(await extractError(res, "Kunne ikke generere client-secret"));
  return readJsonResponse(res);
}

export async function revokeClientSecret(clientId) {
  const res = await apiFetch(`${apiUrl}/api/clients/${encodeURIComponent(clientId)}/client-secret/revoke`, {
    method: "POST",
    headers: authHeaders(),
    credentials: "include",
  });
  if (res.status === 401) { handle401(); throw new Error("Login udløbet"); }
  if (!res.ok)
    throw new Error(await extractError(res, "Kunne ikke tilbagekalde client-secret"));
  return readJsonResponse(res);
}
