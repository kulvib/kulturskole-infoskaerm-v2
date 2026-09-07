# ClientFlow WebSocket protocol contract

The canonical v2 repository has WebSocket transports only for Terminal and Remote Desktop. Livestream v2 uses authenticated HTTP for control/status/upload and HLS for media delivery; it has no browser/agent signalling WebSocket.

## Terminal

- agent: `/api/terminal-agent/clients/{client_id}/ws`
- browser: `/api/terminal/browser/{client_id}/ws`

Terminal uses its isolated Terminal credential/session model. Standard and admin/root sessions share the Terminal domain but remain bound to the requested mode/session and current authorization state.

## Remote Desktop

- control agent: `/api/remote-desktop-agent/clients/{client_id}/control/ws`
- file agent: `/api/remote-desktop-agent/clients/{client_id}/files/ws`
- browser: `/api/remote-desktop/browser/{client_id}/ws`

Remote Desktop uses its isolated credential/session model. Control and file transports are separate and are bound to the same client/session authority.

## Browser authentication

Before opening Terminal or Remote Desktop browser WebSockets, the authenticated frontend requests a short-lived ticket from `POST /api/websocket-tickets/browser`.

The ticket is:

- opaque and random
- one-time use
- bound to the authenticated user and current token version
- bound to one client and exact capability
- transported through `Sec-WebSocket-Protocol`, not the URL
- accepted only with an allowed Origin

The marker subprotocol is `planiq-ws-ticket`.

## Agent authentication

Installed agents authenticate with their domain-owned credential/token boundary. Terminal uses its Terminal auth endpoint. Remote Desktop uses its Remote Desktop auth endpoint. Status/Display/System use the shared HTTP domain-token boundary and do not use WebSockets for their command queue.

## Defensive decoding

`backend/service1/websocket_protocol.py` is the shared decoder for runtime WebSocket JSON messages. Messages must be JSON objects with a non-empty string `type`; oversized/protocol-invalid messages are rejected without exposing stack traces or credentials.

Browser uploads/downloads for Remote Desktop use the dedicated file transport and authenticated HTTP handoff where applicable.

## Change rule

A Terminal or Remote Desktop wire-contract change requires a documented contract/runtime reason and the corresponding physical regression test. Frozen domain protocols are not renamed or refactored solely for cleanup.
