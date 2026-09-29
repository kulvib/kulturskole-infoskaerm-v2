import {
  getActiveAuthSessions,
  revokeAuthSession,
  revokeOtherAuthSessions,
} from "../api";

export function listActiveSessions(signal) {
  return getActiveAuthSessions(signal);
}

export function revokeSession(sessionId, password) {
  return revokeAuthSession(sessionId, password);
}

export function revokeOtherSessions(password) {
  return revokeOtherAuthSessions(password);
}
