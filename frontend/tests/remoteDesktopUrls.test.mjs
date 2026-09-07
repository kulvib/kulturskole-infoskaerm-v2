import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(
  new URL("../src/pages/clientdetailspage/remotedesktop/remoteDesktopUrls.js", import.meta.url),
  "utf8",
);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { buildRemoteDesktopBrowserDownloadUrl, buildRemoteDesktopUploadMultipleUrl } =
  await import(moduleUrl);

test("browser-download URL uses the configured API origin and encodes path values", () => {
  assert.equal(
    buildRemoteDesktopBrowserDownloadUrl("https://display.example/", "client/20", "transfer 1"),
    "https://display.example/api/remote-desktop/clients/client%2F20/files/browser-download/transfer%201",
  );
});

test("multi-file upload URL uses same-origin when API origin is empty", () => {
  assert.equal(
    buildRemoteDesktopUploadMultipleUrl("", "client/20"),
    "/api/remote-desktop/clients/client%2F20/files/upload-multiple",
  );
});
