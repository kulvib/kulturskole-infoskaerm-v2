import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, "..");
const read = (relativePath) => fs.readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");
const DIRECT_API = "https://api.display.planiq.dk";

test("Control Room realtime wait preserves the capability Authorization header", async () => {
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
    const url = String(input);
    calls.push({ input: url, init: { ...init, headers: { ...(init.headers || {}) } } });
    if (url.endsWith("/api/clients/control-room-realtime/capability")) {
      return new Response(JSON.stringify({ token: "realtime-capability", generation: 84 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/clients/control-room-realtime/wait?")) {
      return new Response(JSON.stringify({ generation: 85 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
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
    api.setAuthToken("ordinary-session-token");

    const capability = await api.createControlRoomRealtimeCapability();
    await api.waitForControlRoomRealtime(capability.token, capability.generation, 25);

    const waitCall = calls.find((call) => call.input.includes("/control-room-realtime/wait?"));
    assert.ok(waitCall, "realtime wait request was not made");
    assert.equal(waitCall.init.headers.Authorization, "Bearer realtime-capability");
    assert.equal(waitCall.init.credentials, "omit");
    assert.notEqual(waitCall.init.headers.Authorization, "Bearer ordinary-session-token");
    assert.equal(
      calls.filter((call) => call.input.endsWith("/api/auth/refresh")).length,
      0,
      "capability 401 handling must never enter ordinary browser-session refresh",
    );
  } finally {
    await server.close();
  }
});

test("Ubuntu update UI is command-correlated and kiosk lockdown never claims active from desired state alone", () => {
  const page = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");
  const info = read("src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");

  assert.match(page, /"ubuntu_update_command_id"/);
  assert.match(page, /localOsUpdateCommandId/);
  assert.match(page, /observedCommandId === localOsUpdateCommandId/);
  assert.match(page, /ubuntu_update_error: null/);
  assert.match(page, /ubuntu_update_started_at: null/);
  assert.match(page, /ubuntu_update_finished_at: null/);

  assert.match(info, /requestCommandIdRef/);
  assert.match(info, /res\?\.command_id/);
  assert.match(info, /observedCommandId !== expectedCommandId/);
  assert.match(info, /onStarted\?\.\(\{ optimistic: true, commandId \}\)/);

  assert.match(info, /const lockdownApplied = lockdownStatus === "applied"/);
  assert.match(info, /const lockdownDisabled = lockdownStatus === "disabled"/);
  assert.match(info, /"Ikke bekræftet"/);
  assert.doesNotMatch(
    info,
    /lockdownPending \? "Afventer klient" : lockdownDesired \? "Aktiv" : "Fra"/,
  );
});
