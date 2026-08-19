import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const source = fs.readFileSync(
  path.join(root, "src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx"),
  "utf8"
);

test("Bruger-terminal og Admin-terminal forbliver produktbegreber", () => {
  assert.match(source, /Bruger-terminal/);
  assert.match(source, /Admin-terminal/);
  assert.match(source, /<ToggleButton value="user">Bruger-terminal<\/ToggleButton>/);
  assert.match(source, /<ToggleButton value="admin">Admin-terminal<\/ToggleButton>/);
});

test("Admin-terminal bruger 10 minutters recent step-up uden fritekst-begrundelse", () => {
  const apiSource = fs.readFileSync(path.join(root, "src/api/api.js"), "utf8");
  assert.doesNotMatch(source, /adminReason/);
  assert.doesNotMatch(source, /Begrundelse for Admin-terminal/);
  assert.match(source, /adminPasswordRef/);
  assert.match(source, /Bekræft din adgangskode/);
  assert.match(source, /getAdminTerminalStepUpToken/);
  assert.match(source, /step_up_token/);
  assert.match(source, /Admin-step-up godkendt i 10 minutter/);
  assert.match(source, /Step-up godkendt · op til 10 min/);
  assert.match(source, /type="password"/);
  assert.match(apiSource, /adminTerminalStepUpInMemory/);
  assert.match(apiSource, /hasRecentAdminTerminalStepUp/);
  assert.doesNotMatch(apiSource, /localStorage\.setItem\([^\n]*step.?up/i);
});

test("browserprotokollen forbliver open-input-resize-close", () => {
  assert.match(source, /type: "open"/);
  assert.match(source, /type: "input"/);
  assert.match(source, /type: "resize"/);
  assert.match(source, /type: "close"/);
});


test("Terminal-ruten er kun synlig for superadministrator", () => {
  const appSource = fs.readFileSync(path.join(root, "src/App.jsx"), "utf8");
  assert.match(appSource, /path="\/terminal\/:clientId"[\s\S]*?<AdminRoute requireSuperadmin>[\s\S]*?<ClientTerminalPage \/>/);
});

test("Terminal bruger eget browser-ticket endpoint og ikke Remote Desktops ticket-helper", () => {
  const apiSource = fs.readFileSync(path.join(root, "src/api/api.js"), "utf8");
  assert.match(source, /createTerminalBrowserWsTicket/);
  assert.doesNotMatch(source, /createBrowserWsTicket/);
  assert.match(apiSource, /createTerminalBrowserWsTicket/);
  assert.match(apiSource, /\/terminal\/browser-ticket/);
  assert.match(apiSource, /new Set\(\["remote_desktop"\]\)/);
});


test("Terminal browser websocket reconnecter med frisk ticket efter backend restart", () => {
  assert.match(source, /scheduleReconnect/);
  assert.match(source, /void connectWebSocket\(\)/);
  assert.match(source, /createTerminalBrowserWsTicket/);
  assert.match(source, /Genopretter/);
});
