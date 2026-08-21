import assert from "node:assert/strict";
import test from "node:test";

import { buildFreshInstallDownloadCommand } from "../src/utils/clientflowFreshInstall.js";

const created = {
  code: "CF-ABCD-EFGH-IJKL",
  release_id: "clientflow-1.3.0-seq-1201",
  bundle_sha256: "a".repeat(64),
  fresh_install_authorization: "cf-fresh-v1.payload.signature",
  artifact_url: "/api/enrollment/fresh-install-artifact",
};

test("51N handoff pins backend, release, capability and whole-bundle SHA before installer work", () => {
  const command = buildFreshInstallDownloadCommand(created);
  assert.match(command, /https:\/\/api\.display\.planiq\.dk/);
  assert.match(command, /CF-ABCD-EFGH-IJKL/);
  assert.match(command, /clientflow-1\.3\.0-seq-1201/);
  assert.match(command, /cf-fresh-v1\.payload\.signature/);
  assert.match(command, /expected_bundle_sha256/);
  assert.match(command, /sha256sum --check --strict/);
  assert.match(command, /CLIENTFLOW_RELEASE_PROCEDURE\.md section 5/);
  assert.doesNotMatch(command, /CLIENTFLOW_RELEASE_PROCEDURE\.md section 4/);
  assert.doesNotMatch(command, /github\.com|releases\/latest|onrender\.com/);
});

test("51N handoff is absent without the one-time signed authorization", () => {
  assert.equal(buildFreshInstallDownloadCommand({ ...created, fresh_install_authorization: "" }), "");
});
