import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(frontendRoot, relativePath), "utf8");
}

function handleSubmitSource(source) {
  const start = source.indexOf("const handleSubmit = async");
  assert.notEqual(start, -1, "handleSubmit must exist");
  const end = source.indexOf("\n  };", start);
  assert.notEqual(end, -1, "handleSubmit must have a component-level closing delimiter");
  return source.slice(start, end + 5);
}

const authMutationPages = [
  ["login", "src/LoginPage.jsx"],
  ["forgot password", "src/ForgotPasswordPage.jsx"],
  ["reset password", "src/ResetPasswordPage.jsx"],
  ["own password change", "src/ChangePassword.jsx"],
];

for (const [name, relativePath] of authMutationPages) {
  test(`${name} submit is synchronously single-flight`, () => {
    const source = read(relativePath);
    const handler = handleSubmitSource(source);

    assert.match(source, /const submitInFlightRef = React\.useRef\(false\);/);
    assert.match(handler, /if \(submitInFlightRef\.current\) return;/);

    const lockIndex = handler.indexOf("submitInFlightRef.current = true;");
    const firstAwaitIndex = handler.indexOf("await ");
    const unlockIndex = handler.lastIndexOf("submitInFlightRef.current = false;");

    assert.ok(lockIndex >= 0, "handler must acquire the synchronous submit lock");
    assert.ok(firstAwaitIndex >= 0, "handler must contain an asynchronous boundary");
    assert.ok(
      lockIndex < firstAwaitIndex,
      "submit lock must be acquired before the first await so a second submit cannot race",
    );
    assert.ok(
      unlockIndex > firstAwaitIndex,
      "submit lock must be released after the asynchronous mutation completes",
    );
    assert.match(handler, /finally\s*\{/);
    assert.match(handler, /setLoading\(true\);/);
    assert.match(handler, /setLoading\(false\);/);
  });
}
