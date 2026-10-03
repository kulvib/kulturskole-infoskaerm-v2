# ClientFlow 1.3.30 / 1231 — realtime, firewall and cost hardening

This source iteration hardens the post-1.3.29 physical-acceptance fixes before a new release freeze.

## Fixed architecture constraints

- Every required ClientFlow feature must retain a normal outbound TCP/443 path; no required inbound port, forwarding, UDP, STUN/TURN or municipal firewall exception.
- Neon/Postgres remains durable authority for commands, approvals, configuration, audit and durable outcomes.
- Realtime wake/presence state is ephemeral and does not replace durable command claim/lease/complete semantics.
- UI must not rely on a realtime signal for correctness; bounded HTTP reconciliation remains enabled.
- Existing five display/browser timing contracts remain 10 seconds.
- Embedded release runtime stays Python 3.13.14.

## Measured request/write baseline from the fresh source

The source-level hot-path budget before this change was deterministic:

- Display/System durable command claim: every 5 seconds while idle (`12 claims/minute/domain/client`).
- Calendar conditional fetch: every 15 seconds (`4 requests/minute/client`).
- Control Room list: 2 seconds active / 5 seconds stable.
- Client detail chrome/status projection: 1 second active / 5 seconds stable.
- Remote Desktop browser activity lease: durable renewal every 15 seconds while an RD page remained open.
- Livestream browser viewer heartbeat: every 10 seconds.
- Livestream health: every 1 second.
- Livestream last-segment-info: every 1 second.
- HLS manifest/segment requests traversed database-backed browser authorization.
- RD media: about 6 JPEG frames/second continuously while the visible stream remained open, including unchanged frames.

These values are encoded in the pre-change source and are covered by source/contract tests. Production Neon billing/usage remains an external acceptance measurement and is not fabricated by the repository tests.

## New control-plane behavior

- Display/System agents use WSS wake on 443 as the fast path.
- If WebSocket upgrade is unavailable, agents automatically use outbound HTTPS long-poll.
- The wake contains no command payload. The agent always returns to the durable Neon claim endpoint before executing work.
- A one-minute ordinary claim reconciliation remains as loss/restart recovery.
- The existing 15-second status/liveness cadence is preserved independently from queue claims so UI/liveness does not become slower.
- Calendar delivery uses the same DB-free Display wake as invalidation, conditional ETag fetch after a wake, and a five-minute reconciliation instead of fixed 15-second DB-backed fetching.
- Calendar mutations publish wake only after the durable transaction commits.

## Control Room UI

- A short-lived signed realtime capability is issued after ordinary authenticated UI access.
- The long wait is process-local and does not hold/query a PostgreSQL session.
- It carries only a scoped generation, never client data.
- Agent status and command completion/failure wake the authorized organization/global scope immediately.
- Existing authoritative HTTP snapshots remain the data source.
- Reconciliation polling is reduced to 60 seconds when stable (5 seconds detail-active / 10 seconds list-active) and hidden pages remain paused.

## Livestream

- Viewer heartbeat is reduced from 10 to 25 seconds with a correspondingly bounded lease.
- Authorized heartbeat issues a short-lived signed media capability.
- Hls.js uses that capability for HLS and capability-health reads, eliminating per-segment Postgres authorization on the primary Chromium path.
- Legacy cookie authorization remains as compatibility fallback.
- `/last-segment-info` steady-state polling is removed; HLS fragment events provide segment progress.
- Stable health fallback is reduced from 1 second to 10 seconds.
- Hidden pages stop HLS work; backend lifecycle/grace remains the restart-churn guard.

## Remote Desktop

- Visible active mode remains 6 fps.
- Visible idle mode reduces to 1 fps after 20 seconds.
- Deep visible idle observation reduces to 0.2 fps after 120 seconds.
- Hidden pages stop streaming immediately.
- Mouse/keyboard/wheel activity resumes active mode immediately.
- SHA-256 frame dedup suppresses unchanged JPEG frames, with a sparse refresh guard.
- Browser activity presence is process-local while active; durable DB activity rows are opened/closed for audit but are no longer renewed every 15 seconds.
- Existing control/file transport remains intact; WebRTC is not required and no municipal firewall dependency is introduced.

## Customer handoff lockdown

Fresh enrollment defaults to kiosk lockdown enabled. The customer flow applies and verifies transactional kiosk lockdown before the final reboot. The final physical release gate must therefore prove that Nautilus/DING, kiosk session, `cfadmin` recovery and the 10-second browser/display contracts survive a boot with lockdown already active.

## Scaling boundary

The realtime generation/presence stores are deliberately process-local because production is currently one Render instance / one Uvicorn worker. Horizontal scaling requires replacing these abstractions with shared ephemeral infrastructure (for example Valkey/Redis) before adding workers/instances; Neon is not used as the realtime message broker.
