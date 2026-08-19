export const REMOTE_KEYBOARD_MODE_STANDARD = "standard";
export const REMOTE_KEYBOARD_MODE_MAC = "mac";

const MODIFIER_ONLY_KEYS = new Set([
  "Alt",
  "AltGraph",
  "Control",
  "Meta",
  "Shift",
]);

const NAMED_KEY_MAP = Object.freeze({
  Enter: "Return",
  Escape: "Escape",
  Backspace: "BackSpace",
  Delete: "Delete",
  Tab: "Tab",
  ArrowUp: "Up",
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  Home: "Home",
  End: "End",
  PageUp: "Page_Up",
  PageDown: "Page_Down",
  Insert: "Insert",
  " ": "space",
});

function isPrintableKey(key) {
  return typeof key === "string" && Array.from(key).length === 1;
}

function normalizeCommandKey(key) {
  if (NAMED_KEY_MAP[key]) return NAMED_KEY_MAP[key];
  if (/^F(?:[1-9]|1[0-2])$/.test(String(key || ""))) return key;
  if (/^[a-z]$/i.test(String(key || ""))) return String(key).toLowerCase();
  if (/^[0-9]$/.test(String(key || ""))) return String(key);
  return null;
}

function keyCommand(mainKey, modifiers = []) {
  const normalized = normalizeCommandKey(mainKey);
  if (!normalized) return null;
  return {
    type: "key",
    key: [...modifiers, normalized].join("+"),
  };
}

function modifierList({ ctrl = false, alt = false, shift = false, meta = false } = {}) {
  const parts = [];
  if (ctrl) parts.push("ctrl");
  if (alt) parts.push("alt");
  if (shift) parts.push("shift");
  if (meta) parts.push("super");
  return parts;
}

function macNavigationAction(event) {
  const key = String(event.key || "");

  if (event.metaKey && !event.ctrlKey) {
    if (key === "ArrowLeft") {
      return keyCommand("Home", modifierList({ shift: event.shiftKey }));
    }
    if (key === "ArrowRight") {
      return keyCommand("End", modifierList({ shift: event.shiftKey }));
    }
    if (key === "ArrowUp") {
      return keyCommand("Home", modifierList({ ctrl: true, shift: event.shiftKey }));
    }
    if (key === "ArrowDown") {
      return keyCommand("End", modifierList({ ctrl: true, shift: event.shiftKey }));
    }
  }

  if (event.altKey && !event.metaKey && !event.ctrlKey) {
    if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(key)) {
      return keyCommand(
        key,
        modifierList({ ctrl: true, shift: event.shiftKey }),
      );
    }
    if (["Backspace", "Delete"].includes(key)) {
      return keyCommand(
        key,
        modifierList({ ctrl: true, shift: event.shiftKey }),
      );
    }
  }

  return null;
}

/**
 * Convert a browser KeyboardEvent-like object into the narrow Remote Desktop
 * input protocol. Returning null deliberately suppresses unsupported/system
 * keys instead of forwarding them to the fixed-function root input broker.
 */
export function getRemoteKeyboardAction(event, mode = REMOTE_KEYBOARD_MODE_STANDARD) {
  const key = String(event?.key || "");
  if (!key || MODIFIER_ONLY_KEYS.has(key) || key === "Unidentified" || key === "Dead" || key === "Process") {
    return null;
  }

  const altGraph = Boolean(event?.getModifierState?.("AltGraph"));
  const printable = isPrintableKey(key);
  const macMode = mode === REMOTE_KEYBOARD_MODE_MAC;

  // Layout-generated printable text belongs to the Stage 46e Unicode/Mutter
  // route. AltGr commonly appears as Ctrl+Alt; Mac Option appears as Alt.
  const plainPrintable = printable && !event.ctrlKey && !event.altKey && !event.metaKey;
  const altGraphPrintable = printable && altGraph && !event.metaKey;
  const macOptionPrintable =
    macMode && printable && event.altKey && !event.ctrlKey && !event.metaKey;

  if (plainPrintable || altGraphPrintable || macOptionPrintable) {
    return { type: "text", text: key };
  }

  if (macMode) {
    const navigation = macNavigationAction(event);
    if (navigation) return navigation;

    // Command shortcuts should behave like Ubuntu Ctrl shortcuts. Option is
    // retained as Alt only when it participates in a real command chord.
    if (event.metaKey) {
      return keyCommand(
        key,
        modifierList({
          ctrl: true,
          alt: event.altKey,
          shift: event.shiftKey,
        }),
      );
    }
  }

  // Standard mode preserves browser Ctrl/Alt/Super semantics. Unsupported
  // printable command chords (for example Ctrl+?) are suppressed rather than
  // generating ValueError warnings in the allowlisted uinput broker.
  const modifiers = modifierList({
    ctrl: event.ctrlKey,
    alt: event.altKey && !altGraph,
    shift: event.shiftKey,
    meta: event.metaKey,
  });

  return keyCommand(key, modifiers);
}
