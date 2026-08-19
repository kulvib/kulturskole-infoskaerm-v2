import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) => readFileSync(new URL(`../${relativePath}`, import.meta.url), "utf8");

const auditActions = [
  "client_approved",
  "client_created",
  "client_enrolled",
  "client_organization_changed",
  "client_permanently_deleted",
  "client_restored",
  "client_secret_revoked",
  "client_secret_rotated",
  "client_soft_deleted",
  "enrollment_token_created",
  "enrollment_token_revoked",
  "organization_created",
  "organization_deleted",
  "organization_logo_deleted",
  "organization_logo_updated",
  "organization_name_changed",
  "organization_season_times_applied",
  "organization_season_times_updated",
  "organization_times_updated",
];

test("frontend leaves HLS reset ownership to the client lifecycle and has no retired API exports", () => {
  const apiSource = read("src/api/api.js");
  const livestreamSource = read("src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx");

  assert.doesNotMatch(apiSource, /export function openTerminal\b/);
  assert.doesNotMatch(apiSource, /export function getClientStream\b/);
  assert.doesNotMatch(apiSource, /export (?:async )?function getLivestreamStatus\b/);
  assert.doesNotMatch(apiSource, /export (?:async )?function startLivestream\b/);
  assert.doesNotMatch(apiSource, /export (?:async )?function stopLivestream\b/);
  assert.doesNotMatch(apiSource, /\/api\/livestream\/(?:status|start|stop)\//);
  assert.doesNotMatch(livestreamSource, /\/reset-hls\b/);
  assert.doesNotMatch(
    livestreamSource,
    /\/api\/hls\/\$\{encodeURIComponent\(clientId\)\}\/reset/,
    "browseren må ikke overtage HLS reset/lifecycle fra Ubuntu-klienten",
  );
});

test("all client, organization and enrollment audit actions have Danish UI labels", () => {
  const auditLogSource = read("src/pages/adminpages/AuditLog.jsx");
  const userAdministrationSource = read("src/pages/adminpages/UserAdministration.jsx");

  for (const action of auditActions) {
    assert.match(auditLogSource, new RegExp(`\\b${action}\\s*:`), `AuditLog mangler ${action}`);
    assert.match(
      userAdministrationSource,
      new RegExp(`\\b${action}\\s*:`),
      `UserAdministration mangler ${action}`,
    );
  }
});
