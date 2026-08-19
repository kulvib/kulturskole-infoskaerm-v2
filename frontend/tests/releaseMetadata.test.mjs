import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  createReleaseMetadata,
  resolveReleaseCommit,
  writeReleaseMetadata,
} from "../scripts/writeReleaseMetadata.mjs";

const renderSha = "a".repeat(40);
const githubSha = "b".repeat(40);
const localSha = "c".repeat(40);
const gitSha = "d".repeat(40);

test("Render commit har højeste prioritet", () => {
  const actual = resolveReleaseCommit({
    env: {
      RENDER_GIT_COMMIT: renderSha.toUpperCase(),
      GITHUB_SHA: githubSha,
      PLANIQ_RELEASE_COMMIT: localSha,
    },
    gitResolver: () => gitSha,
  });
  assert.equal(actual, renderSha);
});

test("GitHub SHA bruges i CI når Render SHA mangler", () => {
  assert.equal(resolveReleaseCommit({ env: { GITHUB_SHA: githubSha } }), githubSha);
});

test("Eksplicit lokal releaseværdi understøttes", () => {
  assert.equal(resolveReleaseCommit({ env: { PLANIQ_RELEASE_COMMIT: localSha } }), localSha);
});

test("Lokal Git fallback bruges når miljøvariabler mangler", () => {
  assert.equal(resolveReleaseCommit({ env: {}, gitResolver: () => gitSha }), gitSha);
});

test("Ugyldigt SHA afvises uden fallback", () => {
  assert.throws(
    () => resolveReleaseCommit({ env: { RENDER_GIT_COMMIT: "abc123" }, gitResolver: () => gitSha }),
    /40-tegns Git SHA/,
  );
});

test("Manglende SHA stopper metadata-genereringen", () => {
  assert.throws(
    () => resolveReleaseCommit({ env: {}, gitResolver: () => { throw new Error("no git"); } }),
    /kunne ikke bestemmes/,
  );
});

test("Metadata har stabilt produkt, komponent og commit uden timestamp", () => {
  assert.deepEqual(createReleaseMetadata({ product: "PlanIQ Test", commit: renderSha }), {
    product: "PlanIQ Test",
    component: "frontend",
    commit: renderSha,
  });
});

test("Metadata skrives fysisk og deterministisk til dist-stien", (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "planiq-release-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const outputPath = path.join(directory, "dist", "release.json");

  writeReleaseMetadata({
    product: "PlanIQ Test",
    outputPath,
    env: { PLANIQ_RELEASE_COMMIT: localSha },
  });

  assert.equal(
    fs.readFileSync(outputPath, "utf8"),
    `${JSON.stringify({ product: "PlanIQ Test", component: "frontend", commit: localSha }, null, 2)}\n`,
  );
});
