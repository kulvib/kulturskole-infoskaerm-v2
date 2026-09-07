import assert from "node:assert/strict";
import test from "node:test";

import { getBrowserProcessActionDisabledInfo } from "../src/pages/clientdetailspage/displayActionPolicy.mjs";


test("failed/stopped process remains stoppable while runtime still requests browser", () => {
  assert.equal(getBrowserProcessActionDisabledInfo("stop", false, true), null);
});


test("unknown request state does not infer stop-disabled from process absence", () => {
  assert.equal(getBrowserProcessActionDisabledInfo("stop", false, null), null);
});


test("explicit browser_requested=false disables redundant stop", () => {
  assert.deepEqual(getBrowserProcessActionDisabledInfo("stop", false, false), {
    disabled: true,
    reason: "Kiosk browser er allerede stoppet",
  });
});


test("running process still disables redundant start", () => {
  assert.deepEqual(getBrowserProcessActionDisabledInfo("start", true, true), {
    disabled: true,
    reason: "Kiosk browser kører allerede",
  });
  assert.equal(getBrowserProcessActionDisabledInfo("start", false, true), null);
});
