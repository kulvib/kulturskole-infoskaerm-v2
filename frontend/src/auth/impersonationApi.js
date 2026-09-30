import client, { setAccessTokenInMemory } from "../api/client";
import { clearAdminTerminalStepUp, setSessionExpiresAt } from "../api";

export async function listImpersonationCandidates(signal) {
  const { data } = await client.get("/api/auth/impersonation/candidates", { signal });
  return Array.isArray(data) ? data : [];
}

function applySessionResponse(data) {
  const accessToken = String(data?.access_token || "");
  if (!accessToken || !data?.user) {
    throw new Error("Backend returnerede ikke en gyldig bruger-session");
  }
  setAccessTokenInMemory(accessToken);
  setSessionExpiresAt(data?.session_expires_at || null);
  clearAdminTerminalStepUp();
  return data;
}

export async function startImpersonationSession(targetUserId) {
  const { data } = await client.post(
    "/api/auth/impersonation/start",
    { target_user_id: Number(targetUserId) },
    { sameOrigin: true },
  );
  return applySessionResponse(data);
}

export async function stopImpersonationSession() {
  const { data } = await client.post(
    "/api/auth/impersonation/stop",
    {},
    { sameOrigin: true },
  );
  return applySessionResponse(data);
}
