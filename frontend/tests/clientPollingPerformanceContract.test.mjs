import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const details = read("../src/pages/clientdetailspage/ClientDetailsPage.jsx");
const actions = read("../src/pages/clientdetailspage/ClientDetailsActionsSection.jsx");
const info = read("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");

test("detail hot poll transports canonical presence without a second presence interval", () => {
  assert.match(details, /data\?\.presence/);
  assert.doesNotMatch(details, /getClientPresence\(/);
  assert.doesNotMatch(details, /setInterval\(refreshPresence/);
  assert.match(details, /presenceFetchFailed/);
});

test("ClientFlow deployment polling cannot overlap requests", () => {
  assert.match(actions, /let inFlight = false;[\s\S]*if \(!active \|\| inFlight\) return;[\s\S]*finally \{[\s\S]*inFlight = false;/);
  assert.match(info, /const pollDeployment = async \(\) => \{[\s\S]*if \(!alive \|\| inFlight\) return;[\s\S]*finally \{[\s\S]*inFlight = false;/);
});

test("Ubuntu and local-management polling cannot overlap requests", () => {
  assert.match(info, /const pollUbuntuUpdate = async \(\) => \{[\s\S]*if \(!alive \|\| inFlight\) return;[\s\S]*finally \{[\s\S]*inFlight = false;/);
  assert.match(info, /const pollLocalManagement = async \(\) => \{[\s\S]*if \(cancelled \|\| inFlight\) return;[\s\S]*finally \{[\s\S]*inFlight = false;/);
});
