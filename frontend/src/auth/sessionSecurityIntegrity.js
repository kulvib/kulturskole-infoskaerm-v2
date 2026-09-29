function isIsoTimestamp(value) {
  if (typeof value !== "string" || !value.trim()) return false;
  return Number.isFinite(Date.parse(value));
}

function requireSession(row) {
  if (!row || typeof row !== "object" || Array.isArray(row)) {
    throw new Error("Sessionlisten indeholder et ugyldigt element.");
  }
  if (typeof row.session_id !== "string" || !row.session_id.trim() || row.session_id.length > 64) {
    throw new Error("Sessionlisten indeholder en ugyldig sessionidentitet.");
  }
  if (typeof row.current !== "boolean" || typeof row.impersonation_active !== "boolean") {
    throw new Error("Sessionlisten mangler sikkerhedsmarkeringer.");
  }
  if (!isIsoTimestamp(row.refreshed_at) || !isIsoTimestamp(row.session_expires_at)) {
    throw new Error("Sessionlisten indeholder ugyldige tidsstempler.");
  }
  if (!(row.user_agent == null || typeof row.user_agent === "string")) {
    throw new Error("Sessionlisten indeholder en ugyldig browserbeskrivelse.");
  }
  if (!(row.ip_address == null || typeof row.ip_address === "string")) {
    throw new Error("Sessionlisten indeholder en ugyldig IP-adresse.");
  }
  return row;
}

export function expectActiveSessionsPayload(payload) {
  if (!Array.isArray(payload)) {
    throw new Error("Backend returnerede en ugyldig sessionsliste.");
  }
  const sessions = payload.map(requireSession);
  if (sessions.filter((session) => session.current).length !== 1) {
    throw new Error("Backend kunne ikke identificere den aktuelle session entydigt.");
  }
  return sessions;
}

export function expectSessionRevokePayload(payload) {
  const count = payload?.revoked_count;
  if (!Number.isInteger(count) || count < 0) {
    throw new Error("Backend returnerede et ugyldigt sessionsresultat.");
  }
  return { revoked_count: count };
}
