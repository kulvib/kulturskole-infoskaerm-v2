import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

import { freshInstallOperatorCode } from "../src/utils/clientflowFreshInstall.js";

const created = {
  code: "CF-ABCD-EFGH-IJKL",
  release_id: "clientflow-1.3.18-seq-1219",
  bundle_sha256: "a".repeat(64),
  bundle_size: 220344320,
};

test("fresh-install operator handoff exposes only the short CF code", () => {
  assert.equal(freshInstallOperatorCode(created), "CF-ABCD-EFGH-IJKL");
  assert.equal(freshInstallOperatorCode({}), "");
});

test("fresh-install admin dialog does not expose authorization or shell handoff", async () => {
  const page = await readFile(new URL("../src/pages/adminpages/EnrollmentTokensPage.jsx", import.meta.url), "utf8");
  assert.match(page, /Aktiver ClientFlow/);
  assert.match(page, /kun bruge den korte CF-kode/);
  assert.doesNotMatch(page, /Kopiér authorization/);
  assert.doesNotMatch(page, /Kopiér non-secret handoff/);
  assert.doesNotMatch(page, /skjulte Ubuntu-prompts/);
  assert.doesNotMatch(page, /fresh_install_authorization/);
});
