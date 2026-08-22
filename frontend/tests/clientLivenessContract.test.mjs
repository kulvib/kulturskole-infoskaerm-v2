import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const api = read("../src/api/api.js");
const list = read("../src/pages/ClientInfoPage.jsx");
const details = read("../src/pages/clientdetailspage/ClientDetailsPage.jsx");
const actions = read("../src/pages/clientdetailspage/ClientDetailsActionsSection.jsx");
const info = read("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");

test("frontend consumes only canonical presence for global liveness", () => {
  assert.match(api, /getClientPresence[\s\S]*\/api\/clients\/\$\{id\}\/presence/);
  assert.match(api, /getClientPresence[\s\S]*cache: "no-store"/);
  assert.doesNotMatch(api, /last_seen|\bisOnline\b|\bis_online\b/);
  assert.match(list, /client\?\.presence\?\.is_online === true/);
  assert.match(details, /livePresence\?\.is_online === true/);
  assert.doesNotMatch(details, /client\?\.last_seen|client\?\.isOnline|client\?\.is_online|data\?\.isOnline|data\?\.is_online/);
});

test("live-only legacy actions use canonical Status liveness and not network diagnostics", () => {
  assert.match(actions, /clientOnline !== true/);
  assert.match(actions, /canonical Status-domain/);
  assert.doesNotMatch(actions, /presence\?\.display|presence\?\.system|networkStatusMessage|networkUnavailable/);
  assert.match(info, /clientOnline !== true/);
  assert.doesNotMatch(info, /systemReady|presence\?\.display\?\.ready/);
});

test("ClientFlow deployment is durable and not heartbeat gated", () => {
  const block = info.split("function ClientFlowUpdateControl", 2)[1].split("function getUbuntuStep", 1)[0];
  assert.doesNotMatch(block, /clientOnline/);
  assert.match(block, /requestClientflowDeployment/);
});

test("network diagnostics do not redefine global liveness", () => {
  const block = info.split("function networkStatusLevel", 2)[1].split("function formatDateTime", 1)[0];
  assert.doesNotMatch(block, /isOnline|presence/);
  assert.match(block, /network_has_connection/);
});


test("topbar keeps liveness separate from network diagnostics and presence fetches fail closed", () => {
  const topbar = details.split("function ControlRoomTopbar", 2)[1].split("function SectionTitle", 1)[0];
  assert.match(topbar, /label=\{clientOnline \? "Online" : "Offline"\}/);
  assert.doesNotMatch(topbar, /networkUnavailable \? "Netværk mangler" : clientOnline/);
  assert.match(topbar, /networkUnavailable &&/);
  assert.match(details, /reason: "presence_fetch_failed"/);
  assert.match(details, /is_online: false/);
  assert.match(details, /status:[\s\S]*is_online: false[\s\S]*display:[\s\S]*is_online: false[\s\S]*system:[\s\S]*is_online: false/);
});
