import assert from "node:assert/strict";
import test from "node:test";
import { spawnSync } from "node:child_process";

import { buildFreshInstallDownloadCommand } from "../src/utils/clientflowFreshInstall.js";

const created = {
  code: "CF-ABCD-EFGH-IJKL",
  release_id: "clientflow-1.3.0-seq-1201",
  bundle_sha256: "a".repeat(64),
  bundle_size: 220344320,
  fresh_install_authorization: "cf-fresh-v1.payload.signature",
  artifact_url: "/api/enrollment/fresh-install-artifact",
};

test("51N handoff pins backend, release and whole-bundle SHA without persisting one-time capabilities", () => {
  const command = buildFreshInstallDownloadCommand(created);
  assert.match(command, /https:\/\/api\.display\.planiq\.dk/);
  assert.doesNotMatch(command, /CF-ABCD-EFGH-IJKL/);
  assert.match(command, /clientflow-1\.3\.0-seq-1201/);
  assert.doesNotMatch(command, /cf-fresh-v1\.payload\.signature/);
  assert.match(command, /IFS= read -r CLIENTFLOW_CLIENT_NAME/);
  assert.match(command, /IFS= read -r CLIENTFLOW_LOCALITY/);
  assert.match(command, /IFS= read -r CLIENTFLOW_BOOTSTRAP_NETWORK_UUID/);
  assert.match(command, /IFS= read -r -s ENROLLMENT_CODE/);
  assert.match(command, /IFS= read -r -s FRESH_INSTALL_AUTHORIZATION/);
  assert.match(command, /expected_bundle_sha256/);
  assert.match(command, /APPROVED_BUNDLE_SIZE=220344320/);
  assert.match(command, /Approved bundle size mismatch/);
  assert.match(command, /Approved bundle SHA-256 mismatch/);
  assert.match(command, /tempfile\.mkstemp/);
  assert.match(command, /os\.link\(temporary, bundle\)/);
  assert.match(command, /sha256sum --check --strict/);
  assert.match(command, /CLIENTFLOW_RELEASE_PROCEDURE\.md section 5/);
  assert.doesNotMatch(command, /CLIENTFLOW_RELEASE_PROCEDURE\.md section 4/);
  assert.doesNotMatch(command, /github\.com|releases\/latest|onrender\.com/);
});


test("51N non-secret handoff is valid Bash syntax", () => {
  const command = buildFreshInstallDownloadCommand(created);
  const result = spawnSync("/usr/bin/bash", ["-n"], { input: command, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
});

test("51N handoff is absent without the one-time signed authorization", () => {
  assert.equal(buildFreshInstallDownloadCommand({ ...created, fresh_install_authorization: "" }), "");
});

test("51N fresh-install dialog points to the canonical pinned bootstrap section", async () => {
  const { readFile } = await import("node:fs/promises");
  const page = await readFile(new URL("../src/pages/adminpages/EnrollmentTokensPage.jsx", import.meta.url), "utf8");
  assert.match(page, /CLIENTFLOW_RELEASE_PROCEDURE\.md<\/code> afsnit 5/);
  assert.doesNotMatch(page, /CLIENTFLOW_RELEASE_PROCEDURE\.md<\/code> afsnit 4/);
  assert.match(page, /Kopiér authorization/);
  assert.match(page, /Kopiér non-secret handoff/);
  assert.match(page, /skjulte Ubuntu-prompts/);
});

