import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, "..");
const read = (relativePath) => fs.readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

test("Control Room list uses the narrow summary transport and adaptive cadence", () => {
  const page = read("src/pages/ClientInfoPage.jsx");
  const api = read("src/api/api.js");

  assert.match(api, /export async function getControlRoomClients\(\)/);
  assert.match(api, /\/api\/clients\/control-room-summary/);
  assert.match(page, /getControlRoomClients/);
  assert.doesNotMatch(page, /getMyClients/);
  assert.match(page, /CLIENT_LIST_ACTIVE_POLL_MS = 2_000/);
  assert.match(page, /CLIENT_LIST_IDLE_POLL_MS = 5_000/);
  assert.match(page, /clientListNeedsFastPolling/);
  assert.match(page, /status !== "approved"/);
  assert.match(page, /pendingAction && pendingAction !== "none"/);
  assert.match(page, /client\?\.pending_reboot === true/);
  assert.match(page, /client\?\.pending_shutdown === true/);
  assert.match(page, /client\?\.pending_os_update === true/);
  assert.match(page, /\["wakeup", "rebooting", "updating"\]\.includes\(state\)/);
  assert.doesNotMatch(page, /state !== "normal" && state !== "approved"/);
  assert.match(page, /window\.setTimeout\(async \(\) =>/);
  assert.doesNotMatch(page, /setInterval\([^\n]*fetchClients/);
});

test("Client detail keeps 1s action responsiveness but backs off to 5s when stable", () => {
  const details = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");

  assert.match(details, /CHROME_STATUS_ACTIVE_POLL_MS = 1000/);
  assert.match(details, /CHROME_STATUS_IDLE_POLL_MS = 5000/);
  assert.match(details, /chromeStatusNeedsFastPolling/);
  assert.match(details, /\["wakeup", "rebooting", "updating"\]\.includes\(state\)/);
  assert.doesNotMatch(details, /state !== "normal" && state !== "approved"/);
  assert.match(details, /hotPollFastUntilRef\.current = Date\.now\(\) \+ ACTION_POLL_MAX_MS/);
  assert.match(details, /hotPollWakeRef\.current\(\)/);
  assert.match(details, /Date\.now\(\) < hotPollFastUntilRef\.current/);
  assert.match(details, /\? CHROME_STATUS_ACTIVE_POLL_MS\s*:\s*CHROME_STATUS_IDLE_POLL_MS/);
  assert.match(details, /window\.addEventListener\("focus", wakeWhenVisible\)/);
  assert.match(details, /document\.addEventListener\("visibilitychange", wakeWhenVisible\)/);
});
