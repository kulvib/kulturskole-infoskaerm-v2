import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const dialogSource = fs.readFileSync(
  new URL("../src/pages/calendarpage/DateTimeEditDialog.jsx", import.meta.url),
  "utf8",
);
const clientSource = fs.readFileSync(new URL("../src/api/client.js", import.meta.url), "utf8");

test("calendar dialog uses the central API client for every marked-days request", () => {
  assert.match(dialogSource, /import \{ client \} from "\.\.\/\.\.\/api";/);
  assert.doesNotMatch(dialogSource, /\bfetch\s*\(/);
  assert.doesNotMatch(dialogSource, /\bauthHeaders\b|\bapiUrl\b/);
  assert.equal((dialogSource.match(/client\.get\("\/api\/calendar\/marked-days"/g) || []).length, 3);
  assert.equal((dialogSource.match(/client\.post\("\/api\/calendar\/marked-days"/g) || []).length, 1);
  assert.match(dialogSource, /signal: controller\.signal/);
});

test("central client preserves abort signals and performs one 401 refresh retry", () => {
  assert.match(clientSource, /signal: config\?\.signal/);
  assert.match(clientSource, /if \(res\.status === 401\)/);
  assert.match(clientSource, /const refreshed = await apiPerformBootRefresh\(\)/);
  assert.match(clientSource, /headers: authHeaders/);
});
