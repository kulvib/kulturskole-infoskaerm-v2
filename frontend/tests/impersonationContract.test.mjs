import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("Skift bruger is wired through the central auth/session context", () => {
  const dashboard = read("src/Dashboard.jsx");
  const authContext = read("src/auth/authcontext.jsx");
  const api = read("src/auth/impersonationApi.js");

  assert.match(dashboard, /Skift bruger/);
  assert.match(dashboard, /<ImpersonationBanner/);
  assert.match(dashboard, /<ImpersonationDialog/);
  assert.match(authContext, /isImpersonating/);
  assert.match(authContext, /startImpersonation/);
  assert.match(authContext, /stopImpersonation/);
  assert.match(authContext, /broadcastSessionContextChanged/);
  assert.match(api, /\/api\/auth\/impersonation\/candidates/);
  assert.match(api, /\/api\/auth\/impersonation\/start/);
  assert.match(api, /\/api\/auth\/impersonation\/stop/);
  assert.equal((api.match(/sameOrigin: true/g) || []).length, 2);
});

test("password change is hidden while acting as another user", () => {
  const dashboard = read("src/Dashboard.jsx");
  assert.match(dashboard, /!isImpersonating &&[\s\S]*Skift adgangskode/);
});
