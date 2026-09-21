import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const details = read("../src/pages/clientdetailspage/ClientDetailsPage.jsx");
const info = read("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");
const backend = read("../../backend/service1/routers/clients.py");

test("configuration and diagnostics reuse the shared detail hot-state poll", () => {
  assert.match(details, /const DETAIL_HOT_FIELDS = \[/);
  for (const field of [
    "name",
    "locality",
    "organization_id",
    "kiosk_url",
    "browser_refresh_interval_sec",
    "service_clientflow_status",
    "last_boot_id",
    "livestream_last_error",
    "desktop_lockdown_status",
  ]) {
    assert.match(details, new RegExp(`"${field}"`));
    assert.match(backend, new RegExp(`"${field}"\\s*:`));
  }

  assert.match(details, /setLiveDetailHotFields\(\(prev\) => \(\{ \.\.\.prev, \.\.\.nextDetailHotFields \}\)\)/);
  assert.match(details, /\.\.\.liveDetailHotFields,/);
  assert.doesNotMatch(info, /setInterval\(refreshConfig/);
  assert.doesNotMatch(info, /setInterval\(refreshDiagnostics/);
  assert.doesNotMatch(info, /auto hvert 10 sek\./);
  assert.match(info, /live-status/);
});

test("manual refresh remains available while background full-client polling is removed", () => {
  assert.match(info, /onClick=\{refreshConfigNow\}/);
  assert.match(info, /onClick=\{onRefresh\}/);
  assert.match(info, /Manual refresh remains/);
});
