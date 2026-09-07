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

test("frontend never owns server HLS reset during display changes", () => {
  assert.doesNotMatch(source, /resetHlsFiles/);
  assert.doesNotMatch(source, /\/api\/hls\/[^`]+\/reset/);
  const displayRestartStart = source.indexOf("const restartStreamAfterDisplayChange");
  const displayRestartEnd = source.indexOf("\n  useEffect(() => {", displayRestartStart);
  const displayRestart = source.slice(displayRestartStart, displayRestartEnd);
  assert.match(displayRestart, /ensureStreamStarted/);
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
    source.indexOf("// Backend polling — hvert 2s"),
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
