import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const config = fs.readFileSync(new URL("../src/config/apiConfig.js", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../src/api/api.js", import.meta.url), "utf8");
const render = fs.readFileSync(new URL("../../render.yaml", import.meta.url), "utf8");

test("production data API bypasses static-site rewrite", () => {
  assert.match(
    render,
    /key: VITE_API_URL\s+value: "https:\/\/api\.display\.planiq\.dk"/,
  );
  assert.match(config, /API_URL = API_ORIGIN \? `\$\{API_ORIGIN\}\$\{API_PREFIX\}` : API_PREFIX/);
});

test("refresh-cookie auth remains same-origin while compatibility rewrite stays available", () => {
  assert.match(config, /AUTH_API_URL = `\$\{API_PREFIX\}\/auth`/);
  assert.match(api, /const authApiBase = AUTH_API_URL/);
  assert.doesNotMatch(api, /const authApiBase = buildApiUrl\("\/auth"\)/);
  assert.match(render, /source: \/api\/\*/);
  assert.match(render, /destination: https:\/\/api\.display\.planiq\.dk\/api\/\*/);
});
