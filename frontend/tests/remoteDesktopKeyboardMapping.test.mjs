import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(
  new URL("../src/pages/clientdetailspage/remotedesktop/remoteKeyboardMapping.js", import.meta.url),
  "utf8",
);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const {
  getRemoteKeyboardAction,
  REMOTE_KEYBOARD_MODE_MAC,
  REMOTE_KEYBOARD_MODE_STANDARD,
} = await import(moduleUrl);

function keyEvent(key, overrides = {}) {
  return {
    key,
    ctrlKey: false,
    altKey: false,
    shiftKey: false,
    metaKey: false,
    getModifierState: () => false,
    ...overrides,
  };
}

test("plain Unicode text stays on the text route", () => {
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("æ"), REMOTE_KEYBOARD_MODE_STANDARD),
    { type: "text", text: "æ" },
  );
});

test("AltGr printable characters stay on the text route", () => {
  const event = keyEvent("@", {
    ctrlKey: true,
    altKey: true,
    getModifierState: (name) => name === "AltGraph",
  });
  assert.deepEqual(getRemoteKeyboardAction(event), { type: "text", text: "@" });
});

test("Mac Option printable characters stay on the Unicode text route", () => {
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("€", { altKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "text", text: "€" },
  );
});

test("standard Ctrl+A remains an Ubuntu Ctrl shortcut", () => {
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("a", { ctrlKey: true })),
    { type: "key", key: "ctrl+a" },
  );
});

test("Mac Command shortcuts translate to Ubuntu Ctrl shortcuts", () => {
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("c", { metaKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "key", key: "ctrl+c" },
  );
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("Z", { metaKey: true, shiftKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "key", key: "ctrl+shift+z" },
  );
});

test("Mac Command arrows translate to Ubuntu document/line navigation", () => {
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("ArrowLeft", { metaKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "key", key: "Home" },
  );
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("ArrowRight", { metaKey: true, shiftKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "key", key: "shift+End" },
  );
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("ArrowUp", { metaKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "key", key: "ctrl+Home" },
  );
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("ArrowDown", { metaKey: true, shiftKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "key", key: "ctrl+shift+End" },
  );
});

test("Mac Option arrows translate to Ubuntu Ctrl navigation", () => {
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("ArrowLeft", { altKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "key", key: "ctrl+Left" },
  );
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("ArrowRight", { altKey: true, shiftKey: true }), REMOTE_KEYBOARD_MODE_MAC),
    { type: "key", key: "ctrl+shift+Right" },
  );
});

test("pure modifier/system keydowns are suppressed", () => {
  for (const key of ["Shift", "Control", "Alt", "Meta", "AltGraph", "Dead", "Unidentified", "Process"]) {
    assert.equal(getRemoteKeyboardAction(keyEvent(key)), null);
  }
});

test("unsupported command punctuation is suppressed instead of reaching root broker", () => {
  assert.equal(getRemoteKeyboardAction(keyEvent("?", { ctrlKey: true })), null);
  assert.equal(getRemoteKeyboardAction(keyEvent("+", { altKey: true })), null);
});

test("supported named/function keys remain available", () => {
  assert.deepEqual(getRemoteKeyboardAction(keyEvent("Enter")), { type: "key", key: "Return" });
  assert.deepEqual(
    getRemoteKeyboardAction(keyEvent("F12", { ctrlKey: true })),
    { type: "key", key: "ctrl+F12" },
  );
});
