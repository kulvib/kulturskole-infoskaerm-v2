import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { realtimeSnapshotDelayMs, MIN_REALTIME_SNAPSHOT_SPACING_MS } from "../src/utils/realtimeSnapshotPacing.mjs";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = (file) => fs.readFileSync(path.join(frontendRoot, file), "utf8");

test("first realtime snapshot is immediate; later bursts are paced under 350 ms", () => {
  assert.equal(realtimeSnapshotDelayMs(1000, Number.NEGATIVE_INFINITY), 0);
  assert.equal(realtimeSnapshotDelayMs(1000, 1000), MIN_REALTIME_SNAPSHOT_SPACING_MS);
  assert.equal(realtimeSnapshotDelayMs(1349, 1000), 1);
  assert.equal(realtimeSnapshotDelayMs(1350, 1000), 0);
  assert.equal(realtimeSnapshotDelayMs(5000, 1000), 0);
});

test("many client commits do not require as many full client-list fetches", () => {
  // 1,000 agent state commits in one second: a sequential realtime subscriber
  // can see them through a few coalesced generation changes rather than 1,000
  // full fleet snapshots. The first commit never waits.
  let previous = Number.NEGATIVE_INFINITY;
  let snapshots = 0;
  let time = 0;
  for (let commit = 0; commit < 1000; commit += 1) {
    const eventAt = commit;
    if (eventAt < time) continue; // pending generations coalesce during a fetch
    const delay = realtimeSnapshotDelayMs(eventAt, previous);
    time = eventAt + delay;
    previous = time;
    snapshots += 1;
  }
  assert.ok(snapshots <= 4);
  assert.equal(MIN_REALTIME_SNAPSHOT_SPACING_MS, 350);
});

test("detail uses only a client-authorized scoped capability", () => {
  const api = source("src/api/api.js");
  const list = source("src/pages/ClientInfoPage.jsx");
  const detail = source("src/pages/clientdetailspage/ClientDetailsPage.jsx");
  assert.match(detail, /createControlRoomRealtimeCapability\(client\.id\)/);
  assert.match(list, /createControlRoomRealtimeCapability\(\)/);
  assert.match(api, /client_id=\$\{encodeURIComponent\(clientId\)\}/);
  assert.match(api, /export async function createControlRoomRealtimeCapability\(\)/);
  assert.match(list, /realtimeSnapshotDelayMs\(Date\.now\(\), lastRealtimeSnapshotAt\)/);
  assert.match(list, /await resyncClientsAfterCurrentFetch\(\)/);
});
