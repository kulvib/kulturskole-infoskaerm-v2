import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { shouldAutoOpenTerminalPty } from "../src/pages/clientdetailspage/terminal/terminalOpenPolicy.mjs";

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

test("Admin-terminal autoåbner kun med gyldig recent step-up", () => {
  assert.equal(
    shouldAutoOpenTerminalPty({ mode: "user", clientConnected: true, hasAdminStepUp: false }),
    true
  );
  assert.equal(
    shouldAutoOpenTerminalPty({ mode: "admin", clientConnected: true, hasAdminStepUp: true }),
    true
  );
  assert.equal(
    shouldAutoOpenTerminalPty({ mode: "admin", clientConnected: true, hasAdminStepUp: false }),
    false
  );
  assert.equal(
    shouldAutoOpenTerminalPty({ mode: "admin", clientConnected: false, hasAdminStepUp: true }),
    false
  );
  assert.match(source, /maybeAutoOpenPty\(!!msg\.client_connected\)/);
  assert.match(source, /maybeAutoOpenPty\(true\)/);
  assert.match(source, /Admin-terminal åbnes automatisk uden ny adgangskode/);
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

test("Admin-password kan åbne Admin-terminal med Enter via samme gate som knappen", () => {
  assert.match(source, /const adminOpenDisabled = !connected \|\| !agentConnected \|\| ptyReady \|\| \(!adminStepUpReady && !adminPassword\);/);
  assert.match(source, /const handleAdminPasswordKeyDown = React\.useCallback/);
  assert.match(source, /event\.key !== "Enter" \|\| event\.isComposing \|\| adminOpenDisabled/);
  assert.match(source, /event\.preventDefault\(\);[\s\S]*?openAdminTerminal\(\);/);
  assert.match(source, /onKeyDown=\{handleAdminPasswordKeyDown\}/);
  assert.match(source, /disabled=\{adminOpenDisabled\}/);
});

test("Supportkommandoer dækker canonical V2 host/display/update-diagnostik", () => {
  for (const token of [
    "clientflow-display-agent.service",
    "clientflow-display-runtime.service",
    "clientflow-browser-guard.service",
    "/var/lib/clientflow/display-runtime/configuration.json",
    "/var/lib/clientflow/display-runtime/runtime-status.json",
    "google-chrome-stable --version",
    "clientflow-updater.timer",
    "dpkg --audit",
    "apt-get -o Debug::NoLocking=1 check",
    "/var/run/reboot-required",
    "timedatectl status",
    "resolvectl status",
    "Backend /health svarer ikke",
  ]) {
    assert.match(source, new RegExp(token.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")));
  }
});

test("Bash-parameterudvidelser i supportkommandoer er escaped fra JavaScript template interpolation", () => {
  assert.ok(source.includes('echo "OS: \\${PRETTY_NAME:-ukendt}"'));
  assert.ok(source.includes('if [[ -n "\\${CLIENTFLOW_BASE_URL:-}" ]]'));
  assert.ok(source.includes('"\\${CLIENTFLOW_BASE_URL%/}/health"'));
  assert.doesNotMatch(source, /echo "OS: \${PRETTY_NAME:-ukendt}"/);
});

test("Supportkataloget genintroducerer ikke legacy repair-workarounds", () => {
  for (const forbidden of [
    "Reinstaller Python deps",
    "Reset installer-cache",
    "Reset stale apt-locks",
    "Kør desktop installer",
    "clientflow_service.service",
    "client_remote_desktop_agent.service",
    "clientflow_livestream.service",
  ]) {
    assert.doesNotMatch(source, new RegExp(forbidden.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")));
  }
});
