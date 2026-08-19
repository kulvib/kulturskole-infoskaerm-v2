# ClientFlow WebSocket protocol contract

PlanIQ Display keeps the deployed, versioned ClientFlow wire contracts explicit.
The backend currently exposes two active Terminal/Remote Desktop WebSocket domains plus one
legacy Livestream signalling compatibility socket:

- Terminal v2: `/api/terminal-agent/clients/{client_id}/ws` and `/api/terminal/browser/{client_id}/ws`
- Remote Desktop v2: `/api/remote-desktop-agent/clients/{client_id}/control/ws`, `/api/remote-desktop-agent/clients/{client_id}/files/ws` and `/api/remote-desktop/browser/{client_id}/ws`
- Legacy Livestream signalling compatibility: `/api/ws/livestream/{client_id}`; Livestream v2 agent control/upload uses authenticated HTTP endpoints instead

## Browser authentication and direct transport

The production frontend remains a static site at `https://display.planiq.dk`. Normal HTTP
API calls remain same-origin through `/api/*`, so the existing refresh-cookie and API client
contract is unchanged.

Browser Terminal and Remote Desktop WebSockets connect directly to the backend web service.
Before opening a socket, the authenticated frontend requests a short-lived ticket from
`POST /api/websocket-tickets/browser`. The ticket is a one-time credential and:

- opaque and random;
- valid for one connection only;
- bound to the authenticated user and current `token_version`;
- bound to one `client_id` and one exact capability;
- transported in `Sec-WebSocket-Protocol`, never in the URL;
- accepted only together with an allowed production `Origin`.

The marker subprotocol is `planiq-ws-ticket`. The browser offers the marker followed by the
opaque ticket, and the backend selects only the marker when accepting the connection. The
first-party HttpOnly `access_token` cookie remains a same-origin/local fallback, but browser
query-token authentication is deliberately ignored.

The ticket store is bounded and process-local. This matches the current `render.yaml`
contract of one backend instance worker and the existing process-local Terminal/Remote
Desktop brokers. Horizontal scaling or multiple backend workers requires shared broker and
ticket state before changing that deployment contract.

## Installed ClientFlow agents

Installed ClientFlow agents use domain-owned authentication. Terminal and Livestream retain
their existing agent-token compatibility, while Remote Desktop v2 uses its dedicated
`/api/remote-desktop-auth/token` credential and sends that token as an Authorization bearer
on its separate control and file WebSockets. Agent output is forwarded only to a browser
session for the same client; terminal sessions must also match `mode` (`user` or `admin`).

## Defensive decoding

`backend/service1/websocket_protocol.py` is the single decoder for runtime WebSocket JSON
messages. Every message must be a JSON object with a non-empty string `type`. Oversized
messages close with code `1009`; ordinary protocol errors are returned as neutral error
messages without stack traces or credentials.

Current limits:

- terminal browser messages: staged-script limit plus protocol overhead
- Remote Desktop browser command: 2,100,000 characters
- Remote Desktop v2 control-agent message/frame: 20,000,000 characters
- Remote Desktop v2 file-agent message/frame: 4,500,000 characters
- livestream signalling: `LIVESTREAM_WS_MAX_MESSAGE_BYTES` (default 262,144)

These are broker/message limits. Browser uploads enter through authenticated HTTP and are
then streamed to the RD agent over the dedicated file WebSocket. Agent downloads return over
the file WebSocket and become short-lived, authenticated browser HTTP downloads after backend
size/SHA-256 verification.

## Compatibility rule

A ClientFlow agent protocol change must preserve the currently deployed versioned URLs and
message types unless a separately versioned ClientFlow release is deployed first. CI tests
the shared decoder, ticket binding/single-use behavior, direct browser transport and each
domain's current agent-auth contract.
