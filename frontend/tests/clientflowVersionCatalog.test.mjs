import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const infoSource = fs.readFileSync(
  new URL("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx", import.meta.url),
  "utf8",
);
const apiSource = fs.readFileSync(new URL("../src/api/api.js", import.meta.url), "utf8");
const auditSource = fs.readFileSync(
  new URL("../src/pages/adminpages/AuditLog.jsx", import.meta.url),
  "utf8",
);

test("Control Room only selects stable or supported ClientFlow releases", () => {
  assert.match(infoSource, /\["stable", "supported"\]/);
  assert.match(infoSource, /release\?\.update_allowed === true/);
  assert.match(infoSource, /Seneste stabile/);
  assert.match(infoSource, /Bekræft ClientFlow-nedgradering/);
  assert.match(infoSource, /Begrundelse/);
});

test("ClientFlow update request sends JSON target, confirmation and reason", () => {
  assert.match(
    apiSource,
    /requestClientflowUpdate[\s\S]*headers: authHeaders\(\{ "Content-Type": "application\/json" \}\)/,
  );
  assert.match(apiSource, /target_version: options\.targetVersion \|\| "latest"/);
  assert.match(apiSource, /confirm_downgrade: options\.confirmDowngrade === true/);
  assert.match(apiSource, /reason: options\.reason \|\| null/);
  assert.match(apiSource, /\/api\/clientflow\/releases/);
});

test("manual downgrade has a dedicated Danish audit label", () => {
  assert.match(auditSource, /clientflow_downgrade_requested/);
  assert.match(auditSource, /ClientFlow-nedgradering bestilt/);
});
