import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const remoteDesktop = readFileSync(
  new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url),
  "utf8",
);
const fileManager = readFileSync(
  new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktopFileManager.jsx", import.meta.url),
  "utf8",
);

test("upload uses the HTTP response as the final agent acknowledgement", () => {
  assert.doesNotMatch(remoteDesktop, /transferAckTimerRef/);
  assert.doesNotMatch(remoteDesktop, /pendingUploadResultsRef/);
  assert.match(remoteDesktop, /const expectedCount = Number\(data\?\.count/);
  assert.match(remoteDesktop, /setTransferUploading\(false\);[\s\S]*setTransferFiles\(\[\]\);[\s\S]*file_list_request/);
});

test("file browser only advertises download capabilities supported by v2 FileArea", () => {
  assert.doesNotMatch(remoteDesktop, /file_multi_download_request/);
  assert.doesNotMatch(remoteDesktop, /Pakker .*zip/);
  assert.doesNotMatch(fileManager, /Download valgte/);
  assert.doesNotMatch(fileManager, /Download som zip/);
  assert.match(fileManager, /!activeContextEntry\?\.is_dir && \(/);
});

test("upload conflict UI matches the backend keep-both contract", () => {
  assert.match(fileManager, /value="keep_both">Behold begge/);
  assert.match(fileManager, /value="skip">Spring over/);
  assert.doesNotMatch(fileManager, /value="overwrite"/);
});

test("hidden-file toggle is applied to mapped hidden entries", () => {
  assert.match(fileManager, /if \(!fileBrowserShowHidden && entry\?\.hidden\) return false;/);
  assert.match(remoteDesktop, /show_hidden: !!showHidden/);
});
