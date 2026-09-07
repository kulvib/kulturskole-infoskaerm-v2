const NETWORK_ERROR_MESSAGE = "Netværksfejl – tjek din internetforbindelse og prøv igen.";
const SERVER_ERROR_MESSAGE = "Der opstod en uventet fejl.";

function headerValue(headers, name) {
  if (!headers) return null;
  if (typeof headers.get === "function") {
    return headers.get(name) || headers.get(name.toLowerCase()) || null;
  }
  const lower = String(name).toLowerCase();
  for (const [key, value] of Object.entries(headers)) {
    if (String(key).toLowerCase() === lower) return value == null ? null : String(value);
  }
  return null;
}

function detailFromBody(body, fallback) {
  if (typeof body === "string" && body.trim()) return body.trim();
  if (!body || typeof body !== "object") return fallback;
  if (typeof body.detail === "string" && body.detail.trim()) return body.detail.trim();
  if (typeof body.message === "string" && body.message.trim()) return body.message.trim();
  if (Array.isArray(body.detail)) {
    const message = body.detail
      .map((item) => item?.msg || item?.message || item)
      .filter(Boolean)
      .join(". ");
    if (message) return message;
  }
  return fallback;
}

function requestIdFrom(response, body, error) {
  const bodyId = body?.request_id || body?.requestId;
  if (typeof bodyId === "string" && bodyId.trim()) return bodyId.trim();
  const responseId = headerValue(response?.headers, "x-request-id");
  if (responseId) return responseId.trim();
  const errorId = error?.requestId || error?.request_id;
  return typeof errorId === "string" && errorId.trim() ? errorId.trim() : null;
}

function retryAfterSecondsFrom(response, body, error) {
  const bodyValue = body?.retry_after ?? body?.retryAfter;
  const errorValue = error?.retryAfterSeconds ?? error?.retry_after;
  const header = headerValue(response?.headers, "retry-after");
  const candidate = bodyValue ?? header ?? errorValue;

  if (candidate == null || candidate === "") return null;
  const numeric = Number(candidate);
  if (Number.isFinite(numeric) && numeric >= 0) return Math.ceil(numeric);

  const timestamp = Date.parse(String(candidate));
  if (!Number.isNaN(timestamp)) {
    return Math.max(0, Math.ceil((timestamp - Date.now()) / 1000));
  }
  return null;
}

export class ApiError extends Error {
  constructor(message, options = {}) {
    super(message || options.fallback || "Der opstod en fejl.");
    this.name = "ApiError";
    this.status = Number(options.status || 0);
    this.statusText = options.statusText || "";
    this.data = options.data ?? null;
    this.detail = options.detail ?? null;
    this.requestId = options.requestId || null;
    this.retryAfterSeconds = Number.isFinite(options.retryAfterSeconds)
      ? Math.max(0, Math.ceil(options.retryAfterSeconds))
      : null;
    this.kind = options.kind || (this.status >= 500 ? "server" : this.status === 0 ? "network" : "http");
    this.cause = options.cause;
    this.response = options.response || {
      status: this.status,
      statusText: this.statusText,
      data: this.data,
      headers: options.headers || {},
    };
    this.config = options.config;
  }
}

export function createApiError({ response, body = null, fallback = "Der opstod en fejl.", cause = null } = {}) {
  const status = Number(response?.status || 0);
  const statusText = response?.statusText || "";
  const requestId = requestIdFrom(response, body, cause);
  const retryAfterSeconds = retryAfterSecondsFrom(response, body, cause);
  const detail = detailFromBody(body, fallback);
  const unexpected = status >= 500;
  const message = unexpected && requestId
    ? `${SERVER_ERROR_MESSAGE}\nFejl-id: ${requestId}`
    : unexpected
      ? SERVER_ERROR_MESSAGE
      : detail;
  return new ApiError(message, {
    status,
    statusText,
    data: body,
    detail,
    requestId,
    retryAfterSeconds,
    kind: unexpected ? "server" : status === 0 ? "network" : "http",
    cause,
    response: cause?.response || response,
    headers: response?.headers,
    config: cause?.config,
  });
}

export function normalizeApiError(error, fallback = "Der opstod en fejl.") {
  if (error instanceof ApiError) return error;
  if (error?.name === "AbortError" || error?.name === "TimeoutError" || error?.name === "CanceledError") {
    return error;
  }

  const response = error?.response;
  if (response) {
    const normalized = createApiError({ response, body: response.data ?? null, fallback, cause: error });
    normalized.response = response;
    normalized.config = error?.config;
    return normalized;
  }

  const message = String(error?.message || "");
  const isNetwork =
    !response &&
    (error?.name === "TypeError" || /networkerror|failed to fetch|load failed|network error/i.test(message));

  if (isNetwork) {
    return new ApiError(NETWORK_ERROR_MESSAGE, {
      status: 0,
      detail: NETWORK_ERROR_MESSAGE,
      kind: "network",
      cause: error,
      response: { status: 0, data: { detail: NETWORK_ERROR_MESSAGE }, headers: {} },
      config: error?.config,
    });
  }

  const generic = new ApiError(message || fallback, {
    status: Number(error?.status || 0),
    statusText: error?.statusText || "",
    data: error?.data ?? null,
    detail: error?.detail || message || fallback,
    requestId: requestIdFrom(response, error?.data, error),
    retryAfterSeconds: retryAfterSecondsFrom(response, error?.data, error),
    kind: Number(error?.status || 0) >= 500 ? "server" : "unknown",
    cause: error,
    response: response || error?.response,
    config: error?.config,
  });
  return generic;
}

export function formatApiError(error, fallback = "Der opstod en fejl.") {
  const normalized = normalizeApiError(error, fallback);
  if (normalized?.name === "AbortError" || normalized?.name === "TimeoutError" || normalized?.name === "CanceledError") {
    return normalized.message || fallback;
  }

  let message = normalized?.message || fallback;
  if (normalized?.status >= 500) {
    message = normalized?.requestId
      ? `${SERVER_ERROR_MESSAGE}\nFejl-id: ${normalized.requestId}`
      : SERVER_ERROR_MESSAGE;
  }
  return message;
}

export function formatRateLimitMessage(error, fallback = "For mange forsøg. Prøv igen senere.") {
  const normalized = normalizeApiError(error, fallback);
  const seconds = normalized?.retryAfterSeconds;
  if (!Number.isFinite(seconds) || seconds <= 0) return fallback;
  if (seconds < 60) return `For mange forsøg. Prøv igen om ${seconds} sekunder.`;
  const minutes = Math.ceil(seconds / 60);
  return `For mange forsøg. Prøv igen om ${minutes} ${minutes === 1 ? "minut" : "minutter"}.`;
}

export function isUnexpectedApiError(error) {
  return Number(normalizeApiError(error)?.status || 0) >= 500;
}
