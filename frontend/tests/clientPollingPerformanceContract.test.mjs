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

test("ClientFlow deployment state has one parent-owned database poll", () => {
  assert.match(details, /getClientflowDeployments\(client\.id, \{ limit: 1 \}\)/);
  assert.match(details, /deploymentRefreshInFlightRef\.current/);
  assert.match(details, /setInterval\(refreshClientflowDeployment, CLIENTFLOW_DEPLOYMENT_POLL_MS\)/);
  assert.match(details, /CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES\.has\(clientflowDeploymentState\)/);
  assert.doesNotMatch(actions, /getActiveClientflowDeployment|refreshDeployment|setInterval\([^)]*Deployment/);
  assert.doesNotMatch(info, /getClientflowDeployments|pollDeployment/);
  assert.match(info, /deployment=\{clientflowDeployment\}/);
});

test("Ubuntu and local-management lifecycle reuse the shared chrome-status hot read", () => {
  assert.doesNotMatch(info, /UBUNTU_POLL_MS|pollUbuntuUpdate|pollLocalManagement/);
  assert.match(info, /parent \/chrome-status hot poll already carries every Ubuntu field/);
  assert.match(info, /Local-management lifecycle now arrives on the shared \/chrome-status hot/);
  assert.match(details, /"local_management_status"/);
  assert.match(details, /"local_management_finished_at"/);
  assert.match(info, /onStarted\?\.\(\{ optimistic: true \}\)/);
});
