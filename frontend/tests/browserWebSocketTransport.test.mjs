import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const helperSource = fs.readFileSync(
  new URL("../src/api/browserWebSocket.js", import.meta.url),
  "utf8",
);
const helperUrl = `data:text/javascript;base64,${Buffer.from(helperSource).toString("base64")}`;
const {
  BROWSER_WS_TICKET_PROTOCOL,
  buildBrowserWsProtocols,
  buildBrowserWsUrl,
  normalizeBrowserWsOrigin,
} = await import(helperUrl);

const read = (relativePath) => fs.readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");

test("direct backend origin is normalized to WSS without carrying paths", () => {
  assert.equal(
    normalizeBrowserWsOrigin("https://kulturskole-infosk-rm.onrender.com/api/"),
    "wss://kulturskole-infosk-rm.onrender.com",
  );
  assert.equal(normalizeBrowserWsOrigin("http://localhost:8000"), "ws://localhost:8000");
});

test("browser WebSocket URL uses the direct backend and keeps mode as a normal query", () => {
  const params = new URLSearchParams({ mode: "admin" });
  assert.equal(
    buildBrowserWsUrl(
      "https://backend.example",
      "/api/terminal/browser/22/ws",
      params,
    ),
    "wss://backend.example/api/terminal/browser/22/ws?mode=admin",
  );
});

test("one-time ticket is transported in WebSocket subprotocols and not in URL", () => {
  const ticket = "A".repeat(43);
  assert.deepEqual(buildBrowserWsProtocols(ticket), [BROWSER_WS_TICKET_PROTOCOL, ticket]);
  assert.throws(() => buildBrowserWsProtocols("too-short"), /ugyldig WebSocket-ticket/);
});

test("production source requests a ticket before opening direct browser sockets", () => {
  const apiSource = read("src/api/api.js");
  const terminalSource = read("src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx");
  const remoteSource = read("src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx");
  const renderSource = read("../render.yaml");

  assert.match(apiSource, /\/api\/websocket-tickets\/browser|websocket-tickets\/browser/);
  assert.doesNotMatch(apiSource, /[?&]ticket=/);
  assert.match(terminalSource, /createTerminalBrowserWsTicket/);
  assert.doesNotMatch(terminalSource, /createBrowserWsTicket/);
  assert.match(apiSource, /\/terminal\/browser-ticket/);
  assert.match(terminalSource, /getBrowserWsProtocols/);
  assert.match(remoteSource, /createBrowserWsTicket/);
  assert.match(remoteSource, /getBrowserWsProtocols/);
  assert.match(renderSource, /VITE_WS_API_URL/);
  assert.match(renderSource, /https:\/\/kulturskole-infosk-rm\.onrender\.com/);
});
