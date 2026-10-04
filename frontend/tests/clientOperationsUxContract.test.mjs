import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

function read(relative) {
  return fs.readFileSync(new URL(`../${relative}`, import.meta.url), "utf8");
}

const list = read("src/pages/ClientInfoPage.jsx");
const admin = read("src/pages/adminpages/AdminPage.jsx");
const wall = read("src/pages/adminpages/LivestreamOverview.jsx");
const livestream = read("src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx");
const remoteDesktop = read("src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx");

test("client list exposes deterministic health guidance to admin roles and left-aligns Status", () => {
  assert.match(list, /ClientHealthCell/);
  assert.match(list, /Kontakt en superadministrator/);
  assert.match(list, /<TableCell sx=\{\{ textAlign: "left" \}\}>\s*Status/);
  assert.match(list, /isAdmin && \(\s*<TableCell sx=\{\{ textAlign: "left" \}\}>\s*Fejl/);
  assert.match(list, /required_role/);
});

test("superadmin administration includes a viewport-bounded multi-client livestream wall", () => {
  assert.match(admin, /key: "livestream"[\s\S]*superadminOnly: true[\s\S]*viewerAllowed: false/);
  assert.match(admin, /<LivestreamOverview \/>/);
  assert.match(wall, /IntersectionObserver/);
  assert.match(wall, /source: "superadmin_livestream_wall"/);
  assert.match(wall, /active_viewers/);
  assert.match(wall, /PAGE_HIDDEN_WARM_GRACE_MS = 30_000/);
  assert.match(wall, /viewer-heartbeat/);
  assert.match(wall, /viewer-leave/);
});

test("Livestream keeps an existing player warm for 30 seconds before hidden cleanup", () => {
  assert.match(livestream, /HIDDEN_MEDIA_WARM_GRACE_MS = 30_000/);
  assert.match(livestream, /client_details_livestream_hidden_grace_expired/);
  assert.match(livestream, /setPageVisible\(false\)/);
  assert.doesNotMatch(livestream, /if \(!visible\) \{\s*sendLeaveOnce\("client_details_livestream_hidden"\)/);
});

test("Remote Desktop keeps active capture warm for 30 seconds and never starts a new hidden capture", () => {
  assert.match(remoteDesktop, /RD_HIDDEN_WARM_GRACE_MS = 30_000/);
  assert.match(remoteDesktop, /if \(streamModeRef\.current !== "stopped"\)/);
  assert.match(remoteDesktop, /if \(!pageVisibleRef\.current\) stopStream\(\)/);
  const guardedStarts = remoteDesktop.match(/if \(pageVisibleRef\.current\) startStream\("active", true\)/g) || [];
  assert.equal(guardedStarts.length, 2);
});
