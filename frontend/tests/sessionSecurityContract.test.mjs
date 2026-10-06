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

test("session security page keeps server-owned session controls while matching the Flow layout", () => {
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
  assert.match(page, /maxWidth: 900/);
  assert.match(page, /Se hvor din konto er logget ind, og afslut sessioner du ikke genkender\./);
  assert.match(page, /Log ud på alle andre enheder/);
  assert.match(page, /Ukendt browser\/enhed/);
  assert.match(page, /Denne session/);
  assert.match(page, /Afslut Skift bruger/);
});

test("session payload integrity requires exactly one current session", () => {
  const integrity = read("src/auth/sessionSecurityIntegrity.js");
  assert.match(integrity, /sessions\.filter\(\(session\) => session\.current\)\.length !== 1/);
  assert.match(integrity, /session_expires_at/);
  assert.match(integrity, /impersonation_active/);
});


test("session revocation is synchronously single-flight before the first await", () => {
  const page = read("src/SessionSecurityPage.jsx");
  const start = page.indexOf("const submitReauthentication = async");
  const end = page.indexOf("\n  };", start);
  assert.ok(start >= 0 && end > start, "submitReauthentication handler must exist");

  const handler = page.slice(start, end);
  const guard = handler.indexOf("if (!reauthAction || revokeInFlightRef.current) return;");
  const acquire = handler.indexOf("revokeInFlightRef.current = true;");
  const firstAwait = handler.indexOf("await ");
  const release = handler.lastIndexOf("revokeInFlightRef.current = false;");

  assert.match(page, /const revokeInFlightRef = React\.useRef\(false\);/);
  assert.ok(guard >= 0, "revoke handler must reject a second in-flight submission synchronously");
  assert.ok(acquire > guard && acquire < firstAwait, "in-flight guard must be acquired before the first await");
  assert.ok(release > firstAwait, "in-flight guard must be released after the sensitive action settles");
  assert.match(page, /const closeReauthentication = \(\) => \{[\s\S]*if \(revokeInFlightRef\.current\) return;/);
});


test("access-token renewal is cross-tab serialized and transient refresh failures do not force logout", () => {
  const api = read("src/api/api.js");
  const client = read("src/api/client.js");
  assert.match(api, /navigator\?\.locks/);
  assert.match(api, /REFRESH_LOCK_NAME/);
  assert.match(api, /isTerminalSessionRefreshError/);
  assert.match(api, /if \(isTerminalSessionRefreshError\(error\)\)[\s\S]*window\.location\.href = "\/login"/);
  assert.match(api, /throw error;[\s\S]*return fetchWithFriendlyErrors/);
  assert.match(client, /if \(!isTerminalSessionRefreshError\(error\)\) throw error/);
});
