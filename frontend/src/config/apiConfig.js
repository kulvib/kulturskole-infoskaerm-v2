import { normalizeBrowserWsOrigin } from "../api/browserWebSocket";

// Fælles frontend-konfiguration for API-adresse.
//
// Produktionsprincip:
// - VITE_API_URL er tom.
// - Frontend kalder same-origin /api.
// - Render rewrites /api/* til backend.
//
// Direkte backend-origin bør kun bruges lokalt eller ved fejlsøgning.

export function normalizeConfiguredApiOrigin(value) {
  const raw = String(value ?? "").trim();
  const unquoted = raw.replace(/^(?:[\"'])(.*)(?:[\"'])$/, "$1").trim();
  const lowered = unquoted.toLowerCase();
  if (!unquoted || lowered === "undefined" || lowered === "null") return "";
  return unquoted.replace(/\/+$/, "").replace(/\/api\/?$/, "");
}

export const API_ORIGIN = normalizeConfiguredApiOrigin(import.meta.env.VITE_API_URL);
export const WS_API_ORIGIN = normalizeBrowserWsOrigin(import.meta.env.VITE_WS_API_URL);
export const API_PREFIX = "/api";
export const API_URL = API_ORIGIN ? `${API_ORIGIN}${API_PREFIX}` : API_PREFIX;

export function buildApiUrl(path = "") {
  if (/^https?:\/\//i.test(String(path))) return String(path);

  const raw = String(path || "");
  if (!raw) return API_URL;

  const normalized = raw.startsWith("/") ? raw : `/${raw}`;
  if (normalized === API_PREFIX || normalized.startsWith(`${API_PREFIX}/`)) {
    return `${API_ORIGIN}${normalized}`;
  }
  return `${API_URL}${normalized}`;
}
