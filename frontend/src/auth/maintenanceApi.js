import client from "../api/client";
import { apiUrl } from "../api";
import { createApiError, normalizeApiError } from "../api/apiError";

async function readJson(res, fallback) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) throw createApiError({ response: res, body, fallback });
  return body;
}

export async function getMaintenanceStatus(signal) {
  try {
    const res = await fetch(`${apiUrl}/api/maintenance/status`, {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: { "Cache-Control": "no-store" },
      signal,
    });
    return readJson(res, "Vedligeholdelsesstatus kunne ikke hentes");
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw normalizeApiError(error, "Vedligeholdelsesstatus kunne ikke hentes");
  }
}

export async function updateMaintenanceStatus(payload) {
  const { data } = await client.put("/api/maintenance", payload);
  return data;
}
