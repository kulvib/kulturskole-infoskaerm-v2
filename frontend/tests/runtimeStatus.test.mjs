import assert from "node:assert/strict";
import test from "node:test";

import {
  getUpdateStatusLabel,
  isTerminalUpdateStatus,
  normalizeClientUpdateStatus,
  normalizeRuntimeStatus,
} from "../src/utils/runtimeStatus.mjs";

test("runtime-status normaliseres ens på tværs af Control Room", () => {
  assert.equal(normalizeRuntimeStatus("  UP_TO_DATE  "), "up_to_date");
  assert.equal(normalizeClientUpdateStatus(null), "ready");
});

test("terminalstatus er fælles for update-visninger", () => {
  assert.equal(isTerminalUpdateStatus("success"), true);
  assert.equal(isTerminalUpdateStatus("UP_TO_DATE"), true);
  assert.equal(isTerminalUpdateStatus("installing"), false);
});

test("danske statuslabels er stabile", () => {
  assert.equal(getUpdateStatusLabel("ready"), "Klar");
  assert.equal(getUpdateStatusLabel("up_to_date"), "Allerede opdateret");
  assert.equal(getUpdateStatusLabel("unknown", "Ukendt status"), "Ukendt status");
});
