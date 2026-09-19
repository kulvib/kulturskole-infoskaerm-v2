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

test("AuthProvider boots once and is not coupled to internal route changes", () => {
  const source = read("src/auth/authcontext.jsx");

  assert.match(source, /const \[bootPathname\] = useState\(\(\) => window\.location\.pathname\);/);
  assert.match(source, /if \(isPublicAuthPath\(bootPathname\)\)/);
  assert.match(source, /\}, \[bootPathname\]\);/);
  assert.doesNotMatch(source, /useLocation/);
  assert.doesNotMatch(source, /\}, \[location\.pathname\]\);/);
});

test("ProtectedRoute is a pure UI and role gate without its own auth request", () => {
  const source = read("src/auth/ProtectedRoute.jsx");

  assert.match(source, /const \{ user, isSuperadmin, loading \} = useAuth\(\);/);
  assert.match(source, /if \(loading\) return null;/);
  assert.match(source, /if \(!user\) return <Navigate to="\/login" replace \/>/);
  assert.doesNotMatch(source, /fetch\(/);
  assert.doesNotMatch(source, /performBootRefresh/);
  assert.doesNotMatch(source, /clearAuthToken/);
  assert.doesNotMatch(source, /useEffect/);
});

test("401 refresh and explicit session validation remain centralized", () => {
  const api = read("src/api/api.js");
  const policy = read("src/auth/sessionPolicy.js");

  assert.match(api, /if \(first\.status !== 401 \|\| isPublicOrSessionEndpoint\(url\) \|\| _retried\)/);
  assert.match(api, /await refreshAccessToken\(\);/);
  assert.match(api, /export function refreshSession\(\)/);
  assert.match(policy, /const result = await validateSessionRef\.current\?\.\(\);/);
});

test("backend remains authoritative for active user and token-version on protected requests", () => {
  const backendAuth = fs.readFileSync(
    path.resolve(frontendRoot, "..", "backend", "service1", "auth.py"),
    "utf8",
  );

  assert.match(backendAuth, /user = session\.exec\(select\(User\)\.where\(User\.username == username\)\)\.first\(\)/);
  assert.match(backendAuth, /if not user or not user\.is_active:/);
  assert.match(backendAuth, /_token_version\(payload\.get\("token_version"\)\) != _token_version\(getattr\(user, "token_version", 0\)\)/);
});
