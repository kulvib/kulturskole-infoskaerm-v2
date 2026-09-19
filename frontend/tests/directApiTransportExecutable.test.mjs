import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, "..");
const DIRECT_API = "https://api.display.planiq.dk";

test("production data API is direct while refresh-cookie auth stays same-origin", async () => {
  process.env.VITE_API_URL = DIRECT_API;
  process.env.VITE_WS_API_URL = DIRECT_API;

  const calls = [];
  globalThis.localStorage = {
    getItem() { return null; },
    setItem() {},
    removeItem() {},
  };
  globalThis.window = {
    location: { origin: "https://display.planiq.dk", href: "https://display.planiq.dk/" },
    open() {},
  };
  globalThis.fetch = async (input, init = {}) => {
    calls.push({ input: String(input), init: { ...init } });
    const url = String(input);
    if (url.endsWith("/api/auth/token")) {
      return new Response(JSON.stringify({
        access_token: "direct-api-contract-token",
        session_expires_at: "2026-09-19T18:00:00Z",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.endsWith("/api/auth/refresh")) {
      return new Response(JSON.stringify({
        access_token: "refreshed-direct-api-contract-token",
        session_expires_at: "2026-09-19T18:00:00Z",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const server = await createServer({
    root: FRONTEND_ROOT,
    logLevel: "silent",
    appType: "custom",
    server: { middlewareMode: true },
  });

  try {
    const api = await server.ssrLoadModule("/src/api/api.js");

    calls.length = 0;
    await api.login("contract-user", "contract-password");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].input, "/api/auth/token");
    assert.equal(calls[0].init.credentials, "include");

    calls.length = 0;
    await api.getClients();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].input, `${DIRECT_API}/api/clients/`);
    assert.equal(calls[0].init.credentials, "include");
    assert.equal(
      calls[0].init.headers.Authorization,
      "Bearer direct-api-contract-token",
      "direct API requests must keep Bearer authentication",
    );

    api.clearAuthToken();
    calls.length = 0;
    await api.performBootRefresh();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].input, "/api/auth/refresh");
    assert.equal(calls[0].init.credentials, "include");

    calls.length = 0;
    await api.getChromeStatus(39);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].input, `${DIRECT_API}/api/clients/39/chrome-status`);
    assert.equal(
      calls[0].init.headers.Authorization,
      "Bearer refreshed-direct-api-contract-token",
    );
  } finally {
    await server.close();
  }
});
