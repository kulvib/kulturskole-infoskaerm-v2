# ClientFlow 1.3.30 / 1231 — operator visibility UX closure

This pre-freeze closure adds operator visibility without changing the durable command authority or the ClientFlow embedded runtime.

## Client list health

- `Status` is left-aligned like `Lokalitet`.
- Administrator and superadministrator receive a `Fejl` column.
- The backend builds `health_issues` from already-loaded runtime/diagnostic fields; the list does not add a new DB poll or per-client query.
- Only explicit error evidence is classified. Normal offline/idle states are not automatically faults. Firmware update failures and every canonical service failure used by the Control Room projection are included.
- Every issue contains deterministic operator guidance and a `required_role` boundary. Admin UI instructs the operator to contact a superadministrator when the suggested remediation requires elevated rights.
- `health_issues` is serialized only from the role-aware Control Room summary: administrator and superadministrator receive it; viewer, ordinary user and client principals receive an empty list.

## Superadministrator livestream wall

- Administration contains a superadministrator-only `Livestreams` section.
- Each browser tile has an independent `viewer_id`; the existing Livestream-v2 backend continues to coalesce viewers onto one generation/producer per client.
- `IntersectionObserver` bounds active preview work to tiles near the viewport. Off-screen tiles release viewer/media work instead of creating an unbounded all-client media hot path.
- Viewer heartbeat remains 25 seconds and uses the existing short-lived, principal/session-bound media capability.
- No new steady-state client-list DB poll or HLS segment DB authentication is introduced.

## 30-second warm visibility grace

Livestream and Remote Desktop now use the same operator expectation for a quick browser-tab switch:

1. An already-running stream stays warm for 30 seconds after the document becomes hidden.
2. Returning within 30 seconds reuses the existing player/capture and avoids an unnecessary stop/start handshake.
3. If the page remains hidden beyond 30 seconds, media work is stopped/released.
4. Real page departure/unmount still closes/leaves immediately; the warm grace is for temporary browser visibility loss, not abandoned sessions.
5. Remote Desktop never starts a *new* capture while the document is already hidden, including the connect/agent-ready race.

The normal Livestream backend lease/grace remains recovery/coalescing authority across multiple simultaneous users.
