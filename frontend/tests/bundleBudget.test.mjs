import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { inspectBundle } from "../scripts/checkBundleBudget.mjs";

function createBundle({ entryBytes = 100, chunkBytes = [120, 130, 140, 150, 160] } = {}) {
  const distDir = fs.mkdtempSync(path.join(os.tmpdir(), "planiq-bundle-"));
  fs.mkdirSync(path.join(distDir, ".vite"), { recursive: true });
  fs.mkdirSync(path.join(distDir, "assets"), { recursive: true });
  fs.writeFileSync(
    path.join(distDir, ".vite", "manifest.json"),
    JSON.stringify({ "src/main.jsx": { file: "assets/main.js", isEntry: true } }),
  );
  fs.writeFileSync(path.join(distDir, "assets", "main.js"), Buffer.alloc(entryBytes));
  chunkBytes.forEach((bytes, index) => {
    fs.writeFileSync(path.join(distDir, "assets", `route-${index}.js`), Buffer.alloc(bytes));
  });
  return distDir;
}

test("bundle-budget accepterer route-opdelt frontend", () => {
  const distDir = createBundle();
  const result = inspectBundle({
    distDir,
    entryLimitBytes: 200,
    chunkLimitBytes: 200,
    minJsChunks: 5,
    requiredDynamicEntries: [],
  });
  assert.equal(result.entryBytes, 100);
  assert.ok(result.jsChunkCount >= 5);
});

test("bundle-budget afviser for stor entry", () => {
  const distDir = createBundle({ entryBytes: 250 });
  assert.throws(
    () => inspectBundle({ distDir, entryLimitBytes: 200, chunkLimitBytes: 300, minJsChunks: 5, requiredDynamicEntries: [] }),
    /Frontend-entry overskrider budgettet/,
  );
});

test("bundle-budget afviser monolitisk build", () => {
  const distDir = createBundle({ chunkBytes: [] });
  assert.throws(
    () => inspectBundle({ distDir, entryLimitBytes: 200, chunkLimitBytes: 300, minJsChunks: 5, requiredDynamicEntries: [] }),
    /Code splitting mangler/,
  );
});


test("bundle-budget afviser manglende lazy route", () => {
  const distDir = createBundle();
  assert.throws(
    () => inspectBundle({
      distDir,
      entryLimitBytes: 200,
      chunkLimitBytes: 300,
      minJsChunks: 5,
      requiredDynamicEntries: ["src/pages/calendarpage/CalendarPage.jsx"],
    }),
    /Manglende lazy chunks/,
  );
});
