import { normalizeBrowserWsOrigin } from "../api/browserWebSocket";

// Fælles frontend-konfiguration for API-adresse.
//
// Produktionsprincip:
// - VITE_API_URL peger direkte på den offentlige backend-origin.
// - Almindelige browser-API-kald går derfor uden om Render Static Site rewrite.
// - Auth refresh/login/logout forbliver bevidst same-origin via /api/auth, så den
//   eksisterende HttpOnly refresh-cookie ikke skifter host eller kræver migration.
// - Same-origin /api/* rewrite beholdes som auth/compatibility fallback.

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
// Auth-sessionens HttpOnly refresh-cookie er host-only på frontend-origin.
// Hold derfor login/refresh/logout på same-origin, også når data-API'et er direct.
export const AUTH_API_URL = `${API_PREFIX}/auth`;

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
