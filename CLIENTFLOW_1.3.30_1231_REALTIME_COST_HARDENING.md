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

## Architecture closure after full chat requirements audit

The post-CI audit found additional long-term requirements that were not yet
fully implemented. This source iteration closes those gaps before source freeze.

### Municipal firewall guarantee

Required interactive features no longer depend on WebSocket upgrade support.
Terminal and Remote Desktop keep WSS as the fast path, but automatically fall
back to bounded process-local HTTPS long-poll relays over ordinary outbound TCP
443. The fallback reuses the exact existing WebSocket handlers, tickets,
credentials, authorization, revocation checks, audit and protocol validation;
it is a transport adapter, not a second authority. No inbound client port,
port-forwarding, UDP, STUN/TURN or firewall exception is required.

### Measured source-level Neon request/write budget changes

The pre-change source budget was measured from the fresh source before this
closure. The steady-state changes are:

- Livestream durable command claims: 5-second idle claim cadence (12/min/client)
  becomes realtime wake with a 60-second ordinary durable reconciliation
  (at most 1 idle claim/min/client while wake is healthy).
- Status/Display/System liveness: 15-second observation remains for UI freshness,
  but unchanged state uses locally verified process-memory presence. Durable
  status is written immediately on meaningful state change and at least once
  every 60 seconds for recovery. Naturally volatile uptime/time/load/free-space
  fields cannot manufacture a 15-second durable write.
- Livestream viewer heartbeats: active viewer lease renewal is process-local in
  steady state. Durable viewer rows are written at create/re-open/leave/expiry
  or source transition, rather than rewriting last_seen every 25 seconds.
  Existing authorization/generation reads remain security/lifecycle work and are
  not falsely claimed as eliminated.
- Native HLS receives the same short-lived read-only media capability in an
  HttpOnly/Secure/SameSite cookie scoped to the client HLS path. Current Hls.js
  continues to use the Authorization header. Therefore current browser media
  reads avoid per-segment database authorization without putting a secret in a
  URL; the legacy access-token path remains compatibility fallback only.

The process-local stores are valid only for the current single Render instance /
single Uvicorn worker topology. Horizontal scaling still requires a shared
ephemeral implementation (for example Valkey/Redis) before adding workers.

### Remote Desktop media boundary and measurement

JPEG remains the guaranteed firewall-compatible production media transport.
Capture now sits behind `RemoteDesktopMediaTransport`, with a
`JpegRpcMediaTransport` implementation. Local, non-Neon telemetry records
captured/relayed/unchanged frames, relayed bytes, capture latency and
input-to-next-relayed-frame latency. This provides the baseline required before
any future WebRTC/video-codec experiment can be accepted. WebRTC remains an
optional future optimization and may never become a required municipal-network
dependency.

File activity also keeps Remote Desktop in active mode, so long file operations
do not incorrectly drift into idle/deep-idle capture behavior.

### Retry discipline

Runtime network backoff remains bounded exponential backoff but now adds jitter
to avoid a fleet-wide thundering herd after backend or municipal-network
recovery.

### Deliberate updater boundary

The updater timer is intentionally unchanged in this closure. Release 1.3.29 /
1230 remains fresh-install-only with `update_allowed=false`, and authentic
in-place update has not been physically proven. Changing update discovery before
that bridge is accepted would expand the release risk without benefiting the
current fresh-install acceptance. Updater idle-cost is therefore a documented
future optimization gate when in-place update is allowed again; this source does
not claim that gate has passed.

### Acceptance still required

None of these source changes upgrades 1.3.29 physical acceptance. Release
1.3.30/1231 must still be built from an exact frozen source SHA and physically
prove the candidate bytes, including WSS-blocked HTTPS fallback, post-reboot
lockdown with Nautilus/DING, UI responsiveness, Livestream/Remote Desktop
behavior and measured production Neon impact, before approval or catalog
promotion.

## Final pre-freeze closure after whole-chat audit

Before source freeze, a second whole-chat audit closed the remaining fail-closed
edges without changing the immutable 1.3.29/1230 release bytes:

- Status durable recovery checkpoints are fixed at 60 seconds; deployment
  environment cannot silently stretch the recovery boundary while 15-second
  DB-free liveness remains intact.
- The process-local HTTPS relay has both per-relay and process-global byte
  backpressure, a per-owner concurrency quota, bounded TTL and a 30-second
  closed-relay drain grace so in-flight long polls observe deterministic close
  instead of racing a 404.
- Terminal and Remote Desktop browser HTTPS fallback is bound to the same
  active browser login-session context and token-version as their WebSocket
  fast paths.
- Livestream media capabilities carry the browser-session binding and may never
  outlive the parent login-session; media reads remain locally verifiable and
  do not reintroduce per-segment Postgres authorization.
- Fresh-install customer handoff is staged as
  `awaiting_post_final_reboot_acceptance` before the final reboot. The activated
  runtime marks it `accepted` only on a different boot after observing the
  canonical local Wayland kiosk session, applied/verified kiosk lockdown,
  kiosk/cfadmin privilege separation and executable Nautilus. This automated
  gate complements rather than replaces the required physical DING/Nautilus
  popup acceptance.

The updater optimization remains deliberately deferred until authentic physical
in-place update is proven; WebRTC/codec replacement remains measurement-gated
and optional.
