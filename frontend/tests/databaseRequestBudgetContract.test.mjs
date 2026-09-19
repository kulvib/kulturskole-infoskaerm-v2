import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("action confirmation reuses chrome-status and does not start a second full-client DB poll", () => {
  const details = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");

  assert.match(details, /const hotPollObservationRef = useRef\(/);
  assert.match(details, /receivedAt: Date\.now\(\)/);
  assert.match(details, /observation\.receivedAt < startTime/);
  assert.doesNotMatch(details, /await getClient\(client\.id\)/);
  assert.doesNotMatch(details, /getChromeStatus\(client\.id, \{ fallbackToClient: true \}\)/);
});

test("database topology diagnostics remain secret-free by contract", () => {
  const db = read("../backend/service1/db.py");
  const main = read("../backend/service1/main.py");

  assert.match(db, /"server_side_pooling": bool\(neon_pooler\)/);
  assert.doesNotMatch(db, /"host": host/);
  assert.match(main, /"topology": database_runtime_topology\(\)/);
  assert.match(main, /db;dur=\{db_metrics\.duration_ms:\.2f\}/);
  assert.match(main, /db_metrics\.statement_count/);
  assert.match(main, /db_metrics\.checkout_count/);
});
