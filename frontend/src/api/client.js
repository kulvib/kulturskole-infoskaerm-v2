import { apiUrl, authHeaders, clearAuthToken, performBootRefresh as apiPerformBootRefresh, setAuthToken } from "./api";
import { createApiError, normalizeApiError } from "./apiError";

const NETWORK_ERROR_MESSAGE = "Netværksfejl – tjek din internetforbindelse og prøv igen.";

function buildNetworkError(err) {
  if (err?.name === "AbortError") return err;
  return normalizeApiError(err, NETWORK_ERROR_MESSAGE);
}

async function fetchWithFriendlyErrors(input, init) {
  try {
    return await fetch(input, init);
  } catch (err) {
    throw buildNetworkError(err);
  }
}

function handle401() {
  clearAuthToken();
  localStorage.removeItem("user");
  window.location.href = "/login";
}

function buildUrl(path, params) {
  let clean = String(path || "");
  if (clean === "/api/users/organizations/my") clean = "/api/organizations/";
  if (clean.startsWith("/api/superadmin/organizations")) {
    clean = clean.replace("/api/superadmin/organizations", "/api/organizations");
  }
  const base = clean.startsWith("http://") || clean.startsWith("https://") ? clean : `${apiUrl}${clean}`;
  const url = new URL(base, window.location.origin);
  if (params && typeof params === "object") {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && String(value).trim() !== "") {
        url.searchParams.set(key, String(value));
      }
    });
  }
  return url.toString();
}

function mapUserToBackend(body) {
  if (!body || typeof body !== "object" || body instanceof FormData) return body;
  const next = { ...body };
  if (Object.prototype.hasOwnProperty.call(next, "name") && !Object.prototype.hasOwnProperty.call(next, "full_name")) {
    next.full_name = next.name;
  }
  if (Object.prototype.hasOwnProperty.call(next, "current_password") && !Object.prototype.hasOwnProperty.call(next, "old_password")) {
    next.old_password = next.current_password;
  }
  delete next.name;
  delete next.current_password;
  delete next.collective_agreement_id;
  delete next.send_activation_email;
  return next;
}

function mapUserFromBackend(user) {
  if (!user || typeof user !== "object" || Array.isArray(user)) return user;
  return {
    ...user,
    name: user.name ?? user.full_name ?? "",
    role_display: user.role_display ?? ({
      superadmin: "Superadministrator",
      admin: "Administrator",
      bruger: "Bruger",
      viewer: "Se adgang",
    }[user.role] || user.role),
  };
}

function mapDataFromBackend(data, path) {
  const clean = String(path || "");
  if (clean.includes("/api/users")) {
    return Array.isArray(data) ? data.map(mapUserFromBackend) : mapUserFromBackend(data);
  }
  return data;
}

async function parseResponse(res, path) {
  if (res.status === 401) {
    handle401();
    throw createApiError({
      response: res,
      body: { detail: "Din session er udløbet – log ind igen." },
      fallback: "Din session er udløbet – log ind igen.",
    });
  }

  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      const contentType = res.headers.get("content-type") || "";
      const looksLikeHtml = /^\s*(?:<!doctype\s+html|<html|<head|<body)/i.test(text);
      if (looksLikeHtml || contentType.includes("text/html")) {
        data = {
          _nonJsonHtml: true,
          detail:
            "Backend svarer med HTML i stedet for JSON. Tjek Render rewrite/proxy for /api/* og at VITE_API_URL ikke peger på frontend.",
        };
      } else {
        data = text;
      }
    }
  }

  if (!res.ok) {
    throw createApiError({
      response: res,
      body: data,
      fallback: `HTTP ${res.status}`,
    });
  }

  if (data && typeof data === "object" && data._nonJsonHtml && res.ok) {
    throw new Error(data.detail);
  }

  return { data: mapDataFromBackend(data, path) };
}

async function request(method, path, body, config = {}) {
  const built = buildUrl(path, config?.params);

  const isFormData = body instanceof FormData;
  const headers = authHeaders({ ...(config?.headers || {}) });
  let mappedBody = body;
  if (!isFormData && body !== undefined) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    mappedBody = JSON.stringify(mapUserToBackend(body));
  }

  let res = await fetchWithFriendlyErrors(built, {
    method,
    headers,
    credentials: "include",
    signal: config?.signal,
    body: method === "GET" || method === "HEAD" ? undefined : mappedBody,
  });

  if (res.status === 401) {
    const refreshed = await apiPerformBootRefresh();
    if (refreshed) {
      res = await fetchWithFriendlyErrors(built, {
        method,
        headers: authHeaders({ ...(config?.headers || {}) }),
        credentials: "include",
        signal: config?.signal,
        body: method === "GET" || method === "HEAD" ? undefined : mappedBody,
      });
    }
  }

  return parseResponse(res, path);
}

const client = {
  get(path, config = {}) { return request("GET", path, undefined, config); },
  post(path, body, config = {}) { return request("POST", path, body, config); },
  patch(path, body, config = {}) { return request("PATCH", path, body, config); },
  put(path, body, config = {}) { return request("PUT", path, body, config); },
  delete(path, config = {}) { return request("DELETE", path, undefined, config); },
  request(config = {}) {
    return request(config.method || "GET", config.url, config.data, config);
  },
};

export function setAccessTokenInMemory(token) { setAuthToken(token); }
export function onAuthLogout() { return () => {}; }
export async function clearServerSession() {}
export async function performBootRefresh() { return apiPerformBootRefresh(); }

export default client;
