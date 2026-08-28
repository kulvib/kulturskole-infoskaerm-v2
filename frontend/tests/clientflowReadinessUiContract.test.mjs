import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");

test("Display power is the primary frontend authority and copy is display-specific", () => {
  const page = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");
  const actions = read("src/pages/clientdetailspage/ClientDetailsActionsSection.jsx");

  assert.match(page, /"display_power"/);
  assert.match(page, /displayPower=\{liveClient\?\.display_power \?\? client\?\.display_power \?\? null\}/);
  assert.match(actions, /displayPower = null/);
  assert.match(actions, /displayPowerKnown/);
  assert.match(actions, /label: "Sluk skærm"/);
  assert.match(actions, /label: "Tænd skærm"/);
  assert.doesNotMatch(actions, /label: "Sæt i dvale"/);
  assert.doesNotMatch(actions, /label: "Væk fra dvale"/);
});

test("Ubuntu action copy represents package installation, not a check-only action", () => {
  const info = read("src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");
  assert.match(info, /Installer Ubuntu-opdateringer/);
  assert.doesNotMatch(info, /Tjek\/opdater Ubuntu/);
});

test("orphaned kiosk lockdown control is fail-closed in the frontend", () => {
  const info = read("src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");
  assert.match(info, /Canonical ClientFlow understøtter endnu ikke kiosk lockdown; kontrollen er fail-closed\./);
  assert.doesNotMatch(info, /payload\.desktop_lockdown_enabled\s*=/);
});

test("diagnostic labels point to canonical units instead of obsolete agents", () => {
  const info = read("src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");
  assert.match(info, /Display runtime/);
  assert.match(info, /clientflow-display-runtime\.service/);
  assert.match(info, /clientflow-terminal-agent\.service/);
  assert.match(info, /clientflow-root-terminal-broker\.socket/);
  assert.match(info, /clientflow-remote-desktop-agent\.service/);
  assert.doesNotMatch(info, /clientflow_browser_guard\.service/);
});
