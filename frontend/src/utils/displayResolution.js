export const FALLBACK_DISPLAY_RESOLUTION = Object.freeze({
  width: 1920,
  height: 1080,
  source: "fallback",
});

function toPositiveInt(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const intValue = Math.round(n);
  return intValue > 0 ? intValue : null;
}

function parseResolutionString(value) {
  if (!value || typeof value !== "string") return null;

  const match = value.trim().match(/(\d{3,5})\s*[x×]\s*(\d{3,5})/i);
  if (!match) return null;

  const width = toPositiveInt(match[1]);
  const height = toPositiveInt(match[2]);
  if (!width || !height) return null;

  return { width, height };
}

function dimensions(widthValue, heightValue, source) {
  const width = toPositiveInt(widthValue);
  const height = toPositiveInt(heightValue);

  if (!width || !height) return null;
  return { width, height, source };
}

function fromResolutionString(client, keys, source) {
  for (const key of keys) {
    const parsed = parseResolutionString(client?.[key]);
    if (parsed) return { ...parsed, source };
  }
  return null;
}

export function getEffectiveDisplayResolution(client, liveSize = null) {
  return (
    dimensions(liveSize?.width, liveSize?.height, "live_frame") ||
    dimensions(
      client?.display_resolution_current_width,
      client?.display_resolution_current_height,
      "client_current"
    ) ||
    dimensions(client?.screen_width, client?.screen_height, "client_screen") ||
    fromResolutionString(
      client,
      ["current_resolution", "screen_resolution", "display_resolution_current"],
      "client_current"
    ) ||
    dimensions(
      client?.display_resolution_width,
      client?.display_resolution_height,
      "client_configured"
    ) ||
    fromResolutionString(
      client,
      ["desired_resolution", "configured_resolution", "display_resolution", "resolution"],
      "client_configured"
    ) ||
    FALLBACK_DISPLAY_RESOLUTION
  );
}

export function getDisplayAspectRatio(client, liveSize = null) {
  const resolution = getEffectiveDisplayResolution(client, liveSize);
  return `${resolution.width} / ${resolution.height}`;
}

export function formatDisplayResolution(resolution) {
  if (!resolution?.width || !resolution?.height) return "ukendt opløsning";
  return `${resolution.width}×${resolution.height}`;
}

export const DEFAULT_REMOTE_DESKTOP_CAPTURE_LIMIT = Object.freeze({
  // Native-first for normal desktop displays. The 8K ceiling is only a
  // generic safety bound; getRemoteDesktopCaptureResolution() still keeps
  // the actual client aspect ratio and never upscales above the source.
  maxWidth: 7680,
  maxHeight: 4320,
});

export function getRemoteDesktopCaptureResolution(client, liveSize = null, options = {}) {
  const screen = getEffectiveDisplayResolution(client, liveSize);
  const maxWidth = toPositiveInt(options.maxWidth) || DEFAULT_REMOTE_DESKTOP_CAPTURE_LIMIT.maxWidth;
  const maxHeight = toPositiveInt(options.maxHeight) || DEFAULT_REMOTE_DESKTOP_CAPTURE_LIMIT.maxHeight;

  if (!screen?.width || !screen?.height) {
    return {
      width: maxWidth,
      height: Math.round(maxWidth * 9 / 16),
      screenWidth: maxWidth,
      screenHeight: Math.round(maxWidth * 9 / 16),
      scale: 1,
      source: "capture_fallback",
    };
  }

  const scale = Math.min(1, maxWidth / screen.width, maxHeight / screen.height);
  const width = Math.max(1, Math.round(screen.width * scale));
  const height = Math.max(1, Math.round(screen.height * scale));

  return {
    width,
    height,
    screenWidth: screen.width,
    screenHeight: screen.height,
    scale,
    source: screen.source,
  };
}
