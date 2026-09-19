# ClientFlow database request-budget closure

Date: 2026-09-19

## Scope

This closure follows the database-cost-efficiency package and targets the next
remaining sources of avoidable database work without changing ClientFlow domain
authority or frozen Livestream/Terminal/Remote Desktop runtime contracts.

## Proven findings

1. `ClientDetailsPage` already polls `/api/clients/{id}/chrome-status` every second.
2. During start/stop/sleep/wakeup/reboot/shutdown confirmation it additionally
   polled the full `/api/clients/{id}/` projection every 1.5 seconds.
3. The hot chrome-status projection already contains the pending/state fields
   needed by action confirmation, so the second DB-backed request loop is
   redundant.
4. Existing `Server-Timing` exposed only aggregate application duration; it did
   not show database statement count, database cursor time or pool checkouts.
5. The repository cannot prove whether the secret production `DATABASE_URL`
   uses Neon's pooled (`-pooler`) endpoint. That must be observed from runtime
   configuration without exposing the URL or credentials.

## Changes

- Action confirmation reuses a timestamped observation from the existing
  chrome-status hot poll. A pre-action observation cannot unlock a new action.
- The hot poll no longer requests `fallbackToClient=true`; endpoint failures
  fail closed instead of creating a second full-client request on every failed
  hot poll.
- SQLAlchemy request instrumentation records only counts/durations:
  statements, SELECTs, pool checkouts and aggregate cursor duration. No SQL,
  parameters, hostname or credentials are retained.
- `/api/clients*` `Server-Timing` now includes aggregate DB duration and a
  secret-free statement/checkout description in addition to app duration.
- `/health/db-pool` (superadmin only) now reports secret-free runtime topology:
  backend/driver, provider classification, Neon server-side-pooling boolean,
  SQLAlchemy pool class and configured application-pool limits.
- Startup logs the same secret-free topology and warns, without failing the
  deployment, when a Neon direct endpoint is detected. The secret is not
  modified automatically.

## Deliberately unchanged

- `pool_pre_ping=True` and LIFO application pooling remain enabled. Disconnect
  robustness is not traded away without production evidence.
- Pool size/overflow/recycle values are not changed from guesses.
- Status heartbeat cadence is unchanged.
- Client list and chrome-status cadence are unchanged.
- Livestream, Terminal and Remote Desktop runtime code is untouched.
- The production `DATABASE_URL` secret is not rewritten or inferred.

## Release state

The earlier ClientFlow 1.3.23 / sequence 1224 source freeze is superseded by
post-freeze product changes and must not be released. Release work remains
paused until the performance/database review is closed and a new source identity
is created.
