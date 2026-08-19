import client from "../../api/client";

// Audit-loggen bruger Display-repoets centrale API-klient.
// Det betyder, at et udløbet access-token forsøges fornyet via refresh-cookie,
// før brugeren sendes til login. Det matcher brugeradministration og resten af
// adminområdet og undgår rå fetch-håndtering i denne service.

function appendIfPresent(params, key, value) {
  const clean = String(value ?? "").trim();
  if (clean) params.set(key, clean);
}

async function request(path, { method = "GET", body, signal } = {}) {
  const config = {
    method,
    url: `/api${path}`,
    signal,
    headers: method === "GET"
      ? { "Cache-Control": "no-cache", Pragma: "no-cache" }
      : undefined,
  };
  if (body !== undefined) config.data = body;
  const { data } = await client.request(config);
  return data ?? null;
}

export async function fetchAuditLogs(_token, filters = {}) {
  const params = new URLSearchParams();

  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));

  appendIfPresent(params, "action", filters.action);
  appendIfPresent(params, "entity_type", filters.entity_type);
  appendIfPresent(params, "entity_id", filters.entity_id);
  appendIfPresent(params, "actor_user_id", filters.actor_user_id);
  appendIfPresent(params, "target_user_id", filters.target_user_id);
  appendIfPresent(params, "severity", filters.severity);
  appendIfPresent(params, "is_critical", filters.is_critical);

  // Audit-visningen må aldrig genbruge en browser/CDN-cache efter et nyt login.
  params.set("_ts", String(Date.now()));

  return request(`/superadmin/audit-logs?${params.toString()}`, { signal: filters.signal });
}

export async function fetchAuditLogRetention(_token, opts = {}) {
  return request(`/superadmin/audit-logs/retention?_ts=${Date.now()}`, { signal: opts.signal });
}

export async function cleanupExpiredAuditLogs(_token, opts = {}) {
  return request("/superadmin/audit-logs/cleanup-expired", { method: "POST", body: {}, signal: opts.signal });
}
