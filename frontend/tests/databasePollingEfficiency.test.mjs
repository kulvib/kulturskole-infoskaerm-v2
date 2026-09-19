import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");
}

test("always-on ClientFlow database polling pauses while the browser page is hidden", () => {
  const listPage = read("src/pages/ClientInfoPage.jsx");
  const detailsPage = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");
  const actions = read("src/pages/clientdetailspage/ClientDetailsActionsSection.jsx");
  const info = read("src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");

  assert.match(listPage, /if \(isPageVisible\(\)\) fetchClients\(false, false\);/);
  assert.match(detailsPage, /if \(!isPageVisible\(\)\) \{\s*await new Promise/);
  assert.match(actions, /if \(!active \|\| inFlight \|\| !isPageVisible\(\)\) return;/);
  assert.match(info, /configRefreshInFlightRef\.current \|\| !isPageVisible\(\)/);
  assert.match(info, /diagnosticsRefreshInFlightRef\.current \|\| !isPageVisible\(\)/);
});

test("visibility helper fails open only outside a browser and treats hidden pages as inactive", () => {
  const helper = read("src/utils/pageVisibility.js");
  assert.match(helper, /typeof document === "undefined"/);
  assert.match(helper, /document\.visibilityState !== "hidden"/);
});
