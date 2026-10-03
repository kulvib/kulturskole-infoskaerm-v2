import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, "..");
const read = (relativePath) => fs.readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

test("Control Room list uses DB-free realtime invalidation with bounded reconciliation polling", () => {
  const page = read("src/pages/ClientInfoPage.jsx");
  const api = read("src/api/api.js");

  assert.match(api, /export async function getControlRoomClients\(\)/);
  const controlRoomTransport = api.slice(
    api.indexOf("export async function getControlRoomClients()"),
    api.indexOf("export async function getClient(id)"),
  );
  assert.match(controlRoomTransport, /\/api\/clients\/control-room-summary/);
  assert.match(controlRoomTransport, /cache: "no-store"/);
  assert.match(page, /getControlRoomClients/);
  assert.match(api, /export async function createControlRoomRealtimeCapability\(\)/);
  assert.match(api, /export async function waitForControlRoomRealtime\(/);
  assert.match(api, /\/api\/clients\/control-room-realtime\/wait/);
  assert.match(page, /createControlRoomRealtimeCapability/);
  assert.match(page, /waitForControlRoomRealtime\(capability, generation, 25\)/);
  assert.doesNotMatch(page, /getMyClients/);
  assert.match(page, /CLIENT_LIST_ACTIVE_POLL_MS = 10_000/);
  assert.match(page, /CLIENT_LIST_IDLE_POLL_MS = 60_000/);
  assert.match(page, /clientListNeedsFastPolling/);
  assert.match(page, /status !== "approved"/);
  assert.match(page, /ca\.approval_ready_at !== cb\.approval_ready_at/);
  assert.match(page, /ca\.approval_ready_boot_id !== cb\.approval_ready_boot_id/);
  assert.match(page, /label: "Klar til godkendelse"/);
  assert.match(page, /label: "Afventer reboot"/);
  assert.match(page, /pendingAction && pendingAction !== "none"/);
  assert.match(page, /BUSY_CLIENT_LIST_CHROME_STEPS\.has\(chromeStep\)/);
  assert.match(page, /ca\.chrome_status !== cb\.chrome_status/);
  assert.match(page, /ca\.chrome_color !== cb\.chrome_color/);
  assert.match(page, /browserStatus = String\(client\?\.chrome_status/);
  assert.match(page, /label = `\$\{onlineText\} \/ \$\{stateText\} \/ \$\{browserStatus\}`/);
  assert.match(page, /client\?\.pending_reboot === true/);
  assert.match(page, /client\?\.pending_shutdown === true/);
  assert.match(page, /client\?\.pending_os_update === true/);
  assert.match(page, /\["wakeup", "rebooting", "updating"\]\.includes\(state\)/);
  assert.doesNotMatch(page, /state !== "normal" && state !== "approved"/);
  assert.match(page, /window\.setTimeout\(async \(\) =>/);
  assert.doesNotMatch(page, /setInterval\([^\n]*fetchClients/);
});

test("Client detail uses realtime invalidation with 5s active and 60s reconciliation fallback", () => {
  const details = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");

  assert.match(details, /CHROME_STATUS_ACTIVE_POLL_MS = 5000/);
  assert.match(details, /CHROME_STATUS_IDLE_POLL_MS = 60000/);
  assert.match(details, /chromeStatusNeedsFastPolling/);
  assert.match(details, /createControlRoomRealtimeCapability/);
  assert.match(details, /waitForControlRoomRealtime\(capability, generation, 25\)/);
  assert.match(details, /\["wakeup", "rebooting", "updating"\]\.includes\(state\)/);
  assert.doesNotMatch(details, /state !== "normal" && state !== "approved"/);
  assert.match(details, /hotPollFastUntilRef\.current = Date\.now\(\) \+ ACTION_POLL_MAX_MS/);
  assert.match(details, /hotPollWakeRef\.current\(\)/);
  assert.match(details, /Date\.now\(\) < hotPollFastUntilRef\.current/);
  assert.match(details, /\? CHROME_STATUS_ACTIVE_POLL_MS\s*:\s*CHROME_STATUS_IDLE_POLL_MS/);
  assert.match(details, /window\.addEventListener\("focus", wakeWhenVisible\)/);
  assert.match(details, /document\.addEventListener\("visibilitychange", wakeWhenVisible\)/);
});
