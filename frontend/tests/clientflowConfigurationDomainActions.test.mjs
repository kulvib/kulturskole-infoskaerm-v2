import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");

const info = read("src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");

function configurationPanelSource() {
  const start = info.indexOf("function ConfigurationPanel(");
  const end = info.indexOf("\n\nfunction DiagnosticsPanel", start);
  assert.ok(start >= 0 && end > start, "ConfigurationPanel source must be discoverable");
  return info.slice(start, end);
}

test("configuration uses explicit domain actions instead of one mixed save", () => {
  const panel = configurationPanelSource();

  assert.doesNotMatch(panel, /Gem konfiguration/);
  assert.match(panel, /Gem stamdata/);
  assert.match(panel, /Skift klientnavn/);
  assert.match(panel, /Gem kioskvisning/);
  assert.match(panel, /Flyt organisation/);
  assert.match(panel, /saveLocality/);
  assert.match(panel, /saveClientIdentity/);
  assert.match(panel, /saveKioskDisplay/);
  assert.match(panel, /confirmOrganizationChange/);
});

test("each configuration domain calls only its canonical backend operation", () => {
  const panel = configurationPanelSource();

  assert.match(panel, /apiUpdateClient\(client\.id, \{ locality \}\)/);
  assert.match(panel, /apiRequestLocalHostnameChange\(client\.id, name\)/);
  assert.match(panel, /apiUpdateClient\(client\.id, payload\)/);
  assert.match(panel, /apiChangeClientOrganization\(client\.id, \{/);
  assert.match(panel, /apply_organization_standard_times: true/);
  assert.match(panel, /preserve_manual_times: true/);
});

test("kiosk lockdown is confirmed, asynchronous, and superadmin-write-only", () => {
  const panel = configurationPanelSource();

  assert.match(panel, /\["superadmin", "admin", "viewer"\]\.includes\(role\)/);
  assert.match(panel, /if \(!isSuperadmin \|\| saving\) return/);
  assert.match(panel, /apiUpdateClient\(client\.id, \{ desktop_lockdown_enabled: desktopLockdownEnabled \}\)/);
  assert.match(panel, /Aktivér kiosk lockdown\?/);
  assert.match(panel, /Deaktivér kiosk lockdown\?/);
  assert.match(panel, /desired state/);
  assert.match(panel, /Afventer klient/);
  assert.match(panel, /lockdownDrifted/);
  assert.match(panel, /Drift opdaget/);
  assert.match(panel, /Aktiv og verificeret på kiosk-brugeren/);
});

test("organization move has a dedicated confirmation boundary", () => {
  const panel = configurationPanelSource();

  assert.match(panel, /Flyt klient til anden organisation\?/);
  assert.match(panel, /Organisationens standardtider anvendes på eksisterende tændte dage/);
  assert.match(panel, /Denne handling gemmes separat fra øvrig klientkonfiguration/);
});

test("post-write refresh failure cannot masquerade as a failed mutation", () => {
  const panel = configurationPanelSource();
  assert.match(panel, /The domain mutation has already succeeded/);
  assert.match(panel, /await onSaved\?\.\(payload\)/);
});
