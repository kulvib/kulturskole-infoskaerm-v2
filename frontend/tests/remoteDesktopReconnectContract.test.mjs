import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url),
  "utf8",
);

test("Remote Desktop browser websocket reconnecter automatisk efter backend restart", () => {
  assert.match(source, /reconnectTimerRef/);
  assert.match(source, /reconnectAttemptRef/);
  assert.match(source, /connectRef\.current/);
  assert.match(source, /scheduleReconnect/);
  assert.match(source, /createBrowserWsTicket/);
});
