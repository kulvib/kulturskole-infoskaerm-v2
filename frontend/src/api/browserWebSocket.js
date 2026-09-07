export const BROWSER_WS_TICKET_PROTOCOL = "planiq-ws-ticket";

const TICKET_RE = /^[A-Za-z0-9_-]{32,256}$/;
const SUBPROTOCOL_RE = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;

function unquote(value) {
  return String(value ?? "")
    .trim()
    .replace(/^(?:["'])(.*)(?:["'])$/, "$1")
    .trim();
}

export function normalizeBrowserWsOrigin(value) {
  const raw = unquote(value);
  const lowered = raw.toLowerCase();
  if (!raw || lowered === "undefined" || lowered === "null") return "";

  try {
    const url = new URL(raw);
    if (url.username || url.password || url.search || url.hash) return "";
    if (!["http:", "https:", "ws:", "wss:"].includes(url.protocol)) return "";

    const protocol = url.protocol === "https:" ? "wss:" : url.protocol === "http:" ? "ws:" : url.protocol;
    return `${protocol}//${url.host}`;
  } catch {
    return "";
  }
}

export function buildBrowserWsUrl(origin, path, params = null) {
  const normalizedOrigin = normalizeBrowserWsOrigin(origin);
  if (!normalizedOrigin) throw new Error("WebSocket-backend er ikke konfigureret.");

  const normalizedPath = String(path || "").startsWith("/") ? String(path) : `/${String(path || "")}`;
  const query = params instanceof URLSearchParams ? params.toString() : "";
  return `${normalizedOrigin}${normalizedPath}${query ? `?${query}` : ""}`;
}

export function buildBrowserWsProtocols(ticket, subprotocol = BROWSER_WS_TICKET_PROTOCOL) {
  const normalizedTicket = String(ticket || "").trim();
  const normalizedSubprotocol = String(subprotocol || "").trim();

  if (!TICKET_RE.test(normalizedTicket)) {
    throw new Error("Backend returnerede en ugyldig WebSocket-ticket.");
  }
  if (!SUBPROTOCOL_RE.test(normalizedSubprotocol)) {
    throw new Error("Backend returnerede en ugyldig WebSocket-subprotocol.");
  }

  return [normalizedSubprotocol, normalizedTicket];
}
