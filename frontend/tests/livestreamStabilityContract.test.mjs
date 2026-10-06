import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath) {
  return readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");
}

const source = readFileSync(
  new URL("../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", import.meta.url),
  "utf8",
);

test("ordinary viewer lifecycle delegates lease ownership to Livestream v2", () => {
  assert.doesNotMatch(source, /clearAll:\s*true/);
  assert.doesNotMatch(source, /clear_all:/);
  assert.match(source, /Viewer-presence ejer Livestream-v2 lifecycle server-side/);
  assert.match(source, /\/api\/livestream-v2\/hls\/\$\{encodeURIComponent\(clientId\)\}\/viewer-heartbeat/);
});

test("browser stale watchdog reloads playback without commanding producer restart", () => {
  const staleEffect = source.slice(
    source.indexOf("// Stale watchdog"),
    source.indexOf("// Playback watchdog"),
  );
  assert.match(staleEffect, /setLocalRefreshKey/);
  assert.doesNotMatch(staleEffect, /ensureStreamStarted/);
  assert.doesNotMatch(staleEffect, /livestream_start/);
});

test("HLS.js uses bounded load policies and no deprecated retry knobs", () => {
  for (const token of ["manifestLoadPolicy", "playlistLoadPolicy", "fragLoadPolicy"]) {
    assert.match(source, new RegExp(token));
  }
  for (const deprecated of [
    "manifestLoadingTimeOut",
    "manifestLoadingMaxRetry",
    "fragLoadingTimeOut",
    "fragLoadingMaxRetry",
    "liveBackBufferLength",
  ]) {
    assert.doesNotMatch(source, new RegExp(deprecated));
  }
  assert.doesNotMatch(source, /maxNumRetry:\s*999/);
});


test("control-room navigation does not explicitly stop backend-owned viewer lifecycle", () => {
  const page = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");
  const section = read("src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx");
  assert.doesNotMatch(page, /clientAction\(client\.id,\s*["']livestream_stop["'],\s*["']control_room_back["']/);
  assert.match(page, /Navigation er ikke en eksplicit stophandling/);
  assert.match(section, /Viewer-presence ejer Livestream-v2 lifecycle server-side/);
  assert.match(section, /sendViewerLeave/);
  assert.match(section, /viewer-leave/);
  const terminal = read("src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx");
  assert.doesNotMatch(terminal, /Stop livestream lokalt/);
  assert.doesNotMatch(terminal, /LIVESTREAM_LOCAL_SAFE_STOP_COMMAND/);
});


test("livestream UI uses the dedicated v2 control plane", () => {
  const api = read("src/api/api.js");
  assert.match(source, /\/api\/livestream-v2\/clients\/\$\{encodeURIComponent\(clientId\)\}\/command/);
  assert.doesNotMatch(source, /Start livestream/);
  assert.doesNotMatch(source, /Stop livestream/);
  assert.doesNotMatch(source, /handleExplicitStart/);
  assert.doesNotMatch(source, /handleExplicitStop/);
  assert.match(source, /if \(!resp\.ok\)/);
  assert.match(source, /Viewer-heartbeat fejlede/);
  assert.match(api, /mappedAction\.startsWith\("livestream_"\)/);
  assert.match(api, /\? "livestream-command"/);
  assert.doesNotMatch(api, /\/api\/livestream\/(?:status|start|stop)\//);
});

test("display changes request a fresh Livestream-v2 generation without direct HLS reset", () => {
  assert.doesNotMatch(source, /resetHlsFiles/);
  assert.doesNotMatch(source, /\/api\/hls\/[^`]+\/reset/);
  const displayRestartStart = source.indexOf("const restartStreamAfterDisplayChange");
  const displayRestartEnd = source.indexOf("\n  useEffect(() => {", displayRestartStart);
  const displayRestart = source.slice(displayRestartStart, displayRestartEnd);
  assert.match(displayRestart, /livestream_restart/);
  assert.match(displayRestart, /streamHasBeenActive/);
  assert.doesNotMatch(displayRestart, /ensureStreamStarted/);
  assert.doesNotMatch(displayRestart, /\/reset/);
});

test("livestream stop reason remains authoritative after refresh", () => {
  const page = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");
  const api = read("src/api/api.js");
  assert.match(api, /json\.livestream_stop_reason !== undefined/);
});


test("backend restart recovery keeps health observation alive and recreates HLS after network failure", () => {
  const healthBlock = source.slice(
    source.indexOf("// Poll /health"),
    source.indexOf("// HLS.js lifecycle"),
  );
  const hlsBlock = source.slice(
    source.indexOf("// HLS.js lifecycle"),
    source.indexOf("// Stale watchdog"),
  );
  assert.doesNotMatch(healthBlock, /setServerReady\(true\);[\s\S]{0,200}return;/);
  assert.match(healthBlock, /setServerReady\(false\)/);
  assert.match(hlsBlock, /Hls\.ErrorTypes\.NETWORK_ERROR/);
  assert.match(hlsBlock, /setLocalRefreshKey/);
});

test("livestream surfaces viewer contact immediately and keeps the in-video overlay as the single status authority", () => {
  assert.match(source, /setViewerContactEstablished\(true\)/);
  assert.match(source, /Kontakt til Livestream etableret/);
  assert.match(source, /severity:\s*"success"[\s\S]*Kontakt til Livestream etableret/);
  assert.match(source, /rgba\(6,78,59,0\.72\)/);
  assert.doesNotMatch(source, /\? "Stream offline"[\s\S]*\? "Stream live"[\s\S]*"Afventer stream"/);
});


test("steady-state Livestream media uses short-lived capability and event-driven segment observation", () => {
  assert.equal((source.match(/last-segment-info/g) || []).length, 0);
  assert.match(source, /\/api\/hls-cap\/\$\{clientId\}\/health/);
  assert.match(source, /payload\?\.media_capability/);
  assert.match(source, /Hls\.Events\.FRAG_CHANGED/);
  assert.match(source, /HEALTH_STABLE_POLL_MS = 10_000/);
  assert.match(source, /VIEWER_HEARTBEAT_MS = 25_000/);
  assert.match(source, /visibilitychange/);
  assert.match(source, /!pageVisible \|\| !mediaCapability/);
});

test("hidden Livestream inactivity timer is lifecycle-independent and recoverable", () => {
  assert.match(source, /const hiddenInactivityTimerRef = useRef\(null\)/);
  const visibilityStart = source.indexOf("// Page Visibility is the media-work authority");
  const visibilityEnd = source.indexOf("// Viewer-presence ejer Livestream-v2 lifecycle server-side", visibilityStart);
  assert.ok(visibilityStart >= 0 && visibilityEnd > visibilityStart);
  const visibilityBlock = source.slice(visibilityStart, visibilityEnd);
  assert.match(visibilityBlock, /HIDDEN_INACTIVITY_STOP_MS/);
  assert.match(visibilityBlock, /setInactivityStopped\(true\)/);
  assert.match(visibilityBlock, /setInactivityStopped\(false\)/);
  assert.match(visibilityBlock, /document\.addEventListener\("visibilitychange", applyVisibility\)/);
  assert.match(visibilityBlock, /document\.removeEventListener\("visibilitychange", applyVisibility\)/);
});


test("livestream control and viewer heartbeat use refresh-aware auth and hide raw timeout errors", () => {
  const api = read("src/api/api.js");
  assert.match(source, /authenticatedFetch\(\s*`\$\{apiUrl\}\/api\/livestream-v2\/clients/);
  assert.match(source, /authenticatedFetch\(`\$\{apiUrl\}\/api\/livestream-v2\/hls/);
  assert.match(source, /isRequestTimeout\(err\)/);
  assert.match(source, /Livestream-kontakt er forsinket — prøver igen automatisk/);
  assert.match(api, /export function authenticatedFetch/);
});

test("livestream overview exposes playback latency and fullscreen per tile", () => {
  const overview = read("src/pages/adminpages/LivestreamOverview.jsx");
  assert.match(overview, /FullscreenIcon/);
  assert.match(overview, /requestFullscreen/);
  assert.match(overview, /aria-label=\{`Vis \$\{client\.name/);
  assert.match(overview, /Forsinkelse: \$\{formatLatency\(latencySeconds\)\}/);
  assert.match(overview, /hlsRef\.current\?\.latency/);
  assert.match(overview, /seekable\.end/);
  assert.match(overview, /authenticatedFetch\(`\$\{apiUrl\}\/api\/livestream-v2\/hls/);
});
