import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("Sessioner og sikkerhed is routed through the authenticated user menu", () => {
  const app = read("src/App.jsx");
  const dashboard = read("src/Dashboard.jsx");

  assert.match(app, /sessioner-og-sikkerhed/);
  assert.match(app, /<SessionSecurityPage/);
  assert.match(dashboard, /Sessioner og sikkerhed/);
  assert.match(dashboard, /handleSessionSecurity/);
  assert.match(dashboard, /!isImpersonating &&[\s\S]*Sessioner og sikkerhed/);
});

test("session security API uses server-owned session endpoints and password reauthentication", () => {
  const adapter = read("src/auth/sessionSecurityApi.js");
  const api = read("src/api/api.js");
  const page = read("src/SessionSecurityPage.jsx");

  assert.match(adapter, /getActiveAuthSessions/);
  assert.match(api, /`\$\{authApiBase\}\/sessions`/);
  assert.match(api, /cache: "no-store"/);
  assert.match(api, /`\$\{authApiBase\}\/sessions\/revoke`/);
  assert.match(api, /`\$\{authApiBase\}\/sessions\/revoke-others`/);
  assert.match(api, /password:/);
  assert.match(page, /autoComplete="current-password"/);
  assert.match(page, /slotProps=\{\{ htmlInput: \{ maxLength: 256 \} \}\}/);
  assert.doesNotMatch(page, /inputProps=/);
  assert.match(page, /Denne session/);
  assert.match(page, /Log ud af alle andre sessioner/);
  assert.match(page, /Afslut Skift bruger/);
});

test("session payload integrity requires exactly one current session", () => {
  const integrity = read("src/auth/sessionSecurityIntegrity.js");
  assert.match(integrity, /sessions\.filter\(\(session\) => session\.current\)\.length !== 1/);
  assert.match(integrity, /session_expires_at/);
  assert.match(integrity, /impersonation_active/);
});
