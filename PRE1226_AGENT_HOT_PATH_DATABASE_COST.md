# Pre-1226 agent hot-path / database-cost closure

Status: source candidate from the fresh merged 1.3.24 / seq 1225 main supplied on 2026-09-21.
Branch: `perf/pre1226-agent-hot-path-database-cost`.
Release 1.3.25 / seq 1226 remains paused.

## Scope and invariants

This package reduces continuous PostgreSQL/Neon round-trips in the retained
Status/Display/System/Calendar agent hot paths without changing:

- 15-second Status/Display/System status-report cadence;
- 5-second Display/System command-claim cadence;
- 15-second Calendar delivery poll cadence;
- 120-second shared-domain presence timeout;
- domain credential revocation/token-version checks;
- approved/not-deleted Client lifecycle checks on every authenticated request;
- command authority, lease semantics or fail-closed Display capability gates;
- Calendar completeness validation or local outage cache behavior;
- Livestream, Terminal or Remote Desktop domains;
- release/catalog identity.

## Proven repository root causes and changes

### 1. Shared authorization read the parent Client and then discarded it

`require_shared_agent_token()` already joined `ClientDomainCredential` to
`Client` to enforce credential revocation/token-version plus approved and
not-deleted lifecycle predicates. Status, Display and Calendar hot paths then
issued further Client reads for identity, boot observation, kiosk-lockdown or
Calendar lifecycle checks.

The canonical authorization query now returns a one-request
`SharedAgentAuthorization` containing both the credential and the already
validated Client. The compatibility wrapper still returns only the credential
for call sites that do not need Client state. There is no cross-request cache:
revocation, approval and deletion remain DB-authoritative on every request.

### 2. Every domain heartbeat SELECTed its status row before writing it

`client_domain_status` has a unique `(client_id, domain)` constraint. The
15-second heartbeat nevertheless performed SELECT + INSERT/UPDATE on every
report.

PostgreSQL production and SQLite executable tests now use one atomic
`INSERT .. ON CONFLICT (client_id, domain) DO UPDATE`. Unsupported SQLAlchemy
dialects retain the conservative ORM fallback. Liveness `reported_at` is still
written on every heartbeat; only the read-before-write round-trip is removed.

### 3. Display heartbeat could load the same active command queue twice

`reconcile_display_configuration()` and `reconcile_kiosk_lockdown()` each read
active Display commands. A per-request lazy cache now shares that query only
when either reconciler actually needs it. This preserves the previous early
returns, so clients that do not need the active queue do not gain an
unconditional query.

The kiosk-lockdown reconciler also reuses the Client from the canonical auth
JOIN rather than fetching it again.

### 4. Status heartbeat fetched the Client twice after authorization

Status power/boot observation fetched Client once and the response identity
projection fetched it again. Both now reuse the already-authorized Client from
the same request.

### 5. Calendar delivery used one lifecycle read plus two season reads

An authenticated Display Calendar request previously performed:

1. joined credential/client authorization;
2. `session.get(Client)` lifecycle recheck;
3. current-season CalendarMarking SELECT;
4. next-season CalendarMarking SELECT.

The endpoint now passes the already-authorized Client into the delivery
builder, and both required seasons are fetched in one projected query selecting
only `season` and `markings`. The delivery builder retains a safe standalone
fallback lifecycle check for any future caller that does not come through the
canonical authorization boundary.

## Known steady-state SELECT budget at 100 online clients

This is a repository-level SQL round-trip model, not a Neon billing model. It
ignores SQLAlchemy connection liveness pings, uncommon command mutations and
admin web UI traffic.

Current source cadences are 5 seconds for Display/System command claims and 15
seconds for the three status domains and Calendar.

Conservative pre-package model per client/minute:

- idle Display/System command claims: 48 SELECTs;
- Status heartbeat: 16 SELECTs;
- Display heartbeat: 24 SELECTs;
- System heartbeat: 8 SELECTs;
- Calendar delivery: 16 SELECTs;
- total: ~112 SELECTs/client/minute = ~11,200/minute at 100 clients.

Post-package model:

- idle command claims: 48 SELECTs (unchanged);
- Status heartbeat: 4 SELECTs;
- Display heartbeat: up to 12 SELECTs in the configuration/lockdown path;
- System heartbeat: 4 SELECTs;
- Calendar delivery: 8 SELECTs;
- total conservative budget: ~76 SELECTs/client/minute = ~7,600/minute at 100 clients.

That is approximately 3,600 fewer SELECTs/minute, or ~32%, without changing
polling/freshness behavior. Real Display cost can be lower because the active
command query remains lazy.

## Further optimization candidates deliberately not changed here

These require runtime measurement or change externally observable freshness /
architecture and therefore remain out of this package:

- increasing 5/15-second cadences;
- combining Display status and Calendar delivery into one endpoint;
- long polling / LISTEN-NOTIFY for command delivery;
- a durable Calendar revision/ETag mechanism to avoid repeatedly transferring
  unchanged full calendar JSON;
- changing SQLAlchemy/Neon pool sizing;
- adding/removing indexes without production-like query-plan evidence.

## External best-practice boundary

Repository evidence above proves duplicate/read-before-write round-trips. It
does not prove production query plans or Neon connection configuration.

Current PostgreSQL 18 documentation recommends using `ANALYZE` statistics and
`EXPLAIN`/`EXPLAIN ANALYZE` to inspect the actual workload before index tuning,
and notes that multicolumn indexes should be used selectively. Neon recommends
connection pooling for applications with multiple connections. SQLModel's
FastAPI guidance continues to use a single request-scoped Session. Those are
external guidance items for the later production-like verification; they are
not substituted for repo evidence in this package.

References:
- https://www.postgresql.org/docs/18/sql-explain.html
- https://www.postgresql.org/docs/18/indexes-examine.html
- https://www.postgresql.org/docs/18/indexes-multicolumn.html
- https://neon.com/blog/performance-tips-for-neon-postgres
- https://sqlmodel.tiangolo.com/tutorial/fastapi/session-with-dependency/
