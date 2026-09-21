# Pre-1226 shared-agent request consolidation

Branch target: `perf/pre1226-shared-agent-request-consolidation`

Source identity remains ClientFlow `1.3.24 / seq 1225`. Release `1.3.25 / seq 1226` remains paused.

## Repo-proven root cause

Display and System each use the canonical shared-domain `QueueAgent` with:

- command claim every 5 seconds;
- status report every 15 seconds.

Before this package, a due status report was sent as a separate authenticated HTTP request immediately before the normal command claim. Both requests revalidated the same credential + approved/not-deleted Client against PostgreSQL even though the command claim was going to happen anyway.

The two calls served different functions, but they did not need two authorization round-trips.

## Implementation

`ClaimBody` now has one optional `status_report` field using the exact existing `StatusBody` schema.

For Display and System only, when the 15-second status cadence is due, the QueueAgent embeds the canonical status body in the already-scheduled 5-second claim request. Backend processing:

1. validates credential + Client lifecycle once through `require_shared_agent_context`;
2. applies the exact existing status upsert/reconciliation logic;
3. performs the normal command claim;
4. returns an explicit `status_reported=true` acknowledgement;
5. commits both in the same request transaction.

The client advances its local 15-second heartbeat cadence only after that explicit ACK. If a rolling-upgrade request reaches an older backend that ignores the optional `status_report` field, the ACK is absent and the client immediately sends the historical standalone status PUT. This keeps mixed-version rollout fail-safe.

The normal standalone status endpoints remain unchanged and continue to be used by the Status agent and by forced post-command/error reporting.

Livestream does not opt in and is untouched.

## Preserved invariants

This package deliberately does **not** change:

- Display/System command claim cadence: 5 seconds;
- Display/System status cadence: 15 seconds;
- Status-domain heartbeat cadence: 15 seconds;
- 120-second presence timeout;
- command lease/claim/completion semantics;
- credential revocation, token-version, approval or deletion checks;
- Display desired-configuration or kiosk-lockdown reconciliation;
- post-command forced Display status reporting;
- Calendar, Livestream, Terminal, Remote Desktop or updater architecture;
- release/catalog identity.

A failed combined request does not advance the local status cadence. The existing agent error path still attempts a standalone degraded status report, so a failed claim cannot silently mark a failed heartbeat as successful.

## Database/request budget

Idle baseline, per online client/minute, before this package:

- Display command claims: 12 requests/minute, 24 SELECTs;
- Display status: 4 requests/minute, about 12 SELECTs in the conservative idle model;
- System command claims: 12 requests/minute, 24 SELECTs;
- System status: 4 requests/minute, 4 SELECTs.

Every due Display/System status now shares the authorization SELECT with the claim that was already scheduled for that iteration.

Therefore the repository-level steady-state budget falls by:

- 4 SELECTs/minute/client for Display;
- 4 SELECTs/minute/client for System;
- 8 SELECTs/minute/client total;
- 8 HTTP requests/minute/client total.

Using the previous post-hot-path model of about 76 SELECTs/minute/client, the known shared Status/Display/System/Calendar steady-state model becomes about 68 SELECTs/minute/client, roughly another 10.5% reduction without changing externally observable cadence.

This is a SQL round-trip model, not a claim that Neon charges a fixed price per statement. Neon usage is primarily compute/storage based; reducing always-on round-trips reduces avoidable database work and connection/request pressure.

## Remaining measured candidates

Not changed in this package because they have different risk/authority boundaries:

- Calendar still authenticates and transfers current+next season data every 15 seconds even when unchanged. A revision/conditional-delivery design could reduce JSON/compute work but needs a durable change detector and careful outage semantics.
- The stable ClientFlow updater runs every minute and performs DPoP replay/authentication writes even when no deployment exists. This is a promising next audit target, but replay protection and deployment detection latency must not be weakened.
- Replacing command polling with PostgreSQL LISTEN/NOTIFY or another push channel could reduce idle reads further, but that is an architectural change and is not justified before runtime evidence requires it.

## Gates

Dependency-independent local evidence:

- full `scripts/tests`: 283 passed;
- shared-domain/liveness source contracts: 16 passed;
- new QueueAgent executable piggyback test: included in the scripts suite;
- changed Python modules/tests: `py_compile` PASS.

The executable SQLModel query-count regression is included in `backend/tests/test_shared_domain_database_cost.py`. The local sandbox does not contain the repository's SQLModel backend dependencies, so GitHub CI remains the authoritative executable backend gate.
