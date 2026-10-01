import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, "..");
const DIRECT_API = "https://api.display.planiq.dk";
const FRONTEND_ORIGIN = "https://display.planiq.dk";

test("impersonation keeps cookie-bound mutations same-origin and candidate reads direct", async () => {
  process.env.VITE_API_URL = DIRECT_API;
  process.env.VITE_WS_API_URL = DIRECT_API;

  const calls = [];
  let startAttempts = 0;
  globalThis.localStorage = {
    getItem() { return null; },
    setItem() {},
    removeItem() {},
  };
  globalThis.window = {
    location: { origin: FRONTEND_ORIGIN, href: `${FRONTEND_ORIGIN}/` },
    open() {},
  };
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    calls.push({ input: url, init: { ...init } });

    if (url.endsWith("/api/auth/impersonation/candidates")) {
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.endsWith("/api/auth/impersonation/start")) {
      startAttempts += 1;
      if (startAttempts === 1) {
        return new Response(JSON.stringify({ detail: "Access token expired" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({
        access_token: "impersonated-token",
        session_expires_at: "2026-10-01T01:00:00Z",
        user: { id: 8, username: "target", role: "bruger" },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/api/auth/refresh")) {
      return new Response(JSON.stringify({
        access_token: "refreshed-admin-token",
        session_expires_at: "2026-10-01T01:00:00Z",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/api/auth/impersonation/stop")) {
      return new Response(JSON.stringify({
        access_token: "restored-admin-token",
        session_expires_at: "2026-10-01T01:00:00Z",
        user: { id: 4, username: "admin", role: "superadmin" },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };

  const server = await createServer({
    root: FRONTEND_ROOT,
    logLevel: "silent",
    appType: "custom",
    server: { middlewareMode: true },
  });

  try {
    const api = await server.ssrLoadModule("/src/api/api.js");
    const impersonation = await server.ssrLoadModule("/src/auth/impersonationApi.js");
    api.setAuthToken("admin-token");

    await impersonation.listImpersonationCandidates();
    assert.equal(calls.at(-1).input, `${DIRECT_API}/api/auth/impersonation/candidates`);
    assert.equal(calls.at(-1).init.headers.Authorization, "Bearer admin-token");

    const beforeStart = calls.length;
    await impersonation.startImpersonationSession(8);
    const startCalls = calls.slice(beforeStart);
    assert.equal(startCalls.length, 3);
    assert.equal(startCalls[0].input, `${FRONTEND_ORIGIN}/api/auth/impersonation/start`);
    assert.equal(startCalls[0].init.credentials, "include");
    assert.equal(startCalls[0].init.headers.Authorization, "Bearer admin-token");
    assert.equal(startCalls[1].input, "/api/auth/refresh");
    assert.equal(startCalls[1].init.credentials, "include");
    assert.equal(startCalls[2].input, `${FRONTEND_ORIGIN}/api/auth/impersonation/start`);
    assert.equal(startCalls[2].init.headers.Authorization, "Bearer refreshed-admin-token");

    await impersonation.stopImpersonationSession();
    assert.equal(calls.at(-1).input, `${FRONTEND_ORIGIN}/api/auth/impersonation/stop`);
    assert.equal(calls.at(-1).init.credentials, "include");
    assert.equal(calls.at(-1).init.headers.Authorization, "Bearer impersonated-token");
  } finally {
    await server.close();
  }
});
