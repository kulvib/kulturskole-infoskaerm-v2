import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(new URL("../src/api/apiError.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { createApiError, formatApiError, formatRateLimitMessage, normalizeApiError } = await import(moduleUrl);

test("500 uses a neutral message and shows JSON request_id", () => {
  const error = createApiError({
    response: { status: 500, statusText: "Internal Server Error", headers: new Headers() },
    body: { detail: "sensitive database text", request_id: "req-json-500" },
  });
  assert.equal(error.message, "Der opstod en uventet fejl.\nFejl-id: req-json-500");
  assert.equal(error.requestId, "req-json-500");
  assert.equal(formatApiError(error), "Der opstod en uventet fejl.\nFejl-id: req-json-500");
  assert.doesNotMatch(formatApiError(error), /sensitive database text/);
});

test("response header is used when body has no request id", () => {
  const error = createApiError({
    response: { status: 503, headers: new Headers({ "X-Request-ID": "req-header-503" }) },
    body: { detail: "Databasen er midlertidigt utilgængelig" },
  });
  assert.equal(error.requestId, "req-header-503");
  assert.match(formatApiError(error), /req-header-503/);
});

test("expected validation errors preserve their safe detail", () => {
  const error = createApiError({
    response: { status: 400, headers: new Headers() },
    body: { detail: "Adgangskoden skal være mindst 12 tegn" },
  });
  assert.equal(formatApiError(error), "Adgangskoden skal være mindst 12 tegn");
});

test("Axios-shaped errors remain backward compatible", () => {
  const original = {
    message: "Request failed",
    response: {
      status: 500,
      data: { detail: "internal", request_id: "axios-500" },
      headers: {},
    },
    config: { url: "/api/test" },
  };
  const error = normalizeApiError(original);
  assert.equal(error.response, original.response);
  assert.equal(error.config, original.config);
  assert.equal(error.requestId, "axios-500");
});

test("network failures receive a stable Danish message", () => {
  const error = normalizeApiError(new TypeError("Failed to fetch"));
  assert.equal(error.status, 0);
  assert.match(formatApiError(error), /Netværksfejl/);
});


test("429 preserves Retry-After from JSON and headers", () => {
  const bodyError = createApiError({
    response: { status: 429, headers: new Headers({ "Retry-After": "99" }) },
    body: { detail: "For mange forsøg", retry_after: 42, request_id: "rate-1" },
  });
  assert.equal(bodyError.retryAfterSeconds, 42);
  assert.equal(formatRateLimitMessage(bodyError), "For mange forsøg. Prøv igen om 42 sekunder.");

  const headerError = createApiError({
    response: { status: 429, headers: new Headers({ "Retry-After": "120" }) },
    body: { detail: "For mange forsøg" },
  });
  assert.equal(headerError.retryAfterSeconds, 120);
  assert.equal(formatRateLimitMessage(headerError), "For mange forsøg. Prøv igen om 2 minutter.");
});
