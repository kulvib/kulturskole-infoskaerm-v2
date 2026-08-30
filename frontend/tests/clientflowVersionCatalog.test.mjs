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
  assert.match(infoSource, /selectedRelease\?\.requires_reboot === true/);
  assert.match(infoSource, /kræver én kontrolleret genstart efter grøn ClientFlow-activation/);
  assert.match(infoSource, /Verificér reconnect efter reboot/);
});

test("ClientFlow update request creates a canonical deployment", () => {
  assert.match(
    apiSource,
    /requestClientflowDeployment[\s\S]*\/api\/clients\/\$\{encodeURIComponent\(clientId\)\}\/clientflow-deployments[\s\S]*headers: authHeaders\(\{ "Content-Type": "application\/json" \}\)/,
  );
  assert.match(apiSource, /target_version: targetVersion/);
  assert.match(apiSource, /targetVersion\.toLowerCase\(\) === "latest"/);
  assert.match(infoSource, /targetVersion: resolvedSelectedVersion/);
  assert.match(apiSource, /confirm_downgrade: options\.confirmDowngrade === true/);
  assert.match(apiSource, /reason: options\.reason \|\| null/);
  assert.match(apiSource, /getClientflowDeployments/);
  assert.match(apiSource, /getActiveClientflowDeployment/);
  assert.match(apiSource, /cancelClientflowDeployment/);
  assert.match(apiSource, /\/api\/clientflow\/releases/);
  assert.doesNotMatch(apiSource, /\/api\/clients\/\$\{clientId\}\/clientflow-update/);
});

test("canonical deployment events have Danish audit labels", () => {
  assert.match(auditSource, /clientflow_deployment_authorized/);
  assert.match(auditSource, /ClientFlow-deployment autoriseret/);
  assert.match(auditSource, /clientflow_deployment_cancelled/);
  assert.match(auditSource, /ClientFlow-deployment annulleret/);
  assert.match(auditSource, /ClientFlow-version bestilt \(historisk\)/);
});
