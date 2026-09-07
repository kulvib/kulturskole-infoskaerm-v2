import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const remoteDesktopUrl = new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url);

test("Remote Desktop asks the physical client for native geometry", async () => {
  const source = await readFile(remoteDesktopUrl, "utf8");
  assert.match(source, /type: "start_stream",\s*\n\s*\/\/[^\n]*\n[^]*?native: true/);
  assert.doesNotMatch(source, /width: remoteCaptureResolution\.width/);
  assert.doesNotMatch(source, /screen_width: remoteCaptureResolution\.screenWidth/);
  assert.match(source, /Stream aktiv \${geometry\.width}x\${geometry\.height}/);
});
