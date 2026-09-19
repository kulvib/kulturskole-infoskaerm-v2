# ClientFlow shared live-state polling closure

Date: 2026-09-19

Baseline: canonical `main` commit `1305c1447b9b47c767396833a16e54b9af139d0d`.

## Problem

After the earlier database-cost and request-observability work, ClientDetails still had three duplicated database-backed polling paths:

1. `ClientDetailsActionsSection` polled active ClientFlow deployment state every 2.5 seconds even while no deployment was active.
2. `ClientFlowUpdateControl` independently loaded/polled deployment state, so an active deployment could be polled by two sibling components at the same time.
3. Ubuntu update and local-management controls started their own database-backed polls although the existing 1-second `/chrome-status` read already carried the Ubuntu projection and already computed the local-management System projection.

The deployment history call also returned the complete deployment history although the Control Room needs only the newest row for live status.

## Closure

- ClientFlow deployment state has one owner in `ClientDetailsPage`, the closest common parent of Actions and Info.
- Inactive deployment state is fetched once on client entry and revalidated on focus/visibility return; it has no periodic idle timer.
- Active deployment state has one 2.5-second parent poll with an in-flight guard.
- Both child sections consume the same deployment snapshot.
- The frontend requests only the newest deployment row with `limit=1`; the backend keeps the existing unbounded default contract for callers that need history and validates optional limits to 1..100.
- Ubuntu update state reacts to the existing `/chrome-status` live props and uses a local timeout only; no second full-client refresh loop runs during the update.
- Local-management status fields are transported on `/chrome-status` from the System projection that is already loaded for the hot read. No additional SQL query is introduced.
- The separate 2-second local-management polling loop is removed. Manual local-management refresh remains available.
- Backend action endpoints remain the durable concurrency authority, so a stale UI cannot bypass the no-active-deployment invariant.

## Request-budget effect

On an open superadmin ClientDetails page:

- idle ClientFlow deployment polling: 24 requests/minute -> 0 periodic requests/minute (one entry/focus revalidation only),
- active ClientFlow deployment polling: up to 48 requests/minute across two siblings -> one 24 requests/minute parent poll,
- active Ubuntu update extra full-client polling: 12 requests/minute -> 0,
- active local-management extra polling: 30 requests/minute -> 0.

The existing 1-second `/chrome-status` hot read remains unchanged in cadence because it is the shared live observation path and is responsible for responsive kiosk/system UI. Its SQL query budget remains unchanged by exposing local-management fields already computed from the existing System batch.

These are request-count reductions, not a claim of equal percentage cost reduction in Neon. Actual compute impact remains measurable through the previously added Server-Timing and DB runtime topology instrumentation.

## Validation

Local gates available in the working environment:

- `node --test frontend/tests/clientPollingPerformanceContract.test.mjs frontend/tests/databasePollingEfficiency.test.mjs`: green.
- `PYTHONPATH=backend:client/runtime:client/release/lib python -m pytest -q scripts/tests`: green.
- `python -m compileall -q backend/service1 scripts/tests`: green.
- `git diff --check`: green.

The full frontend dependency-backed suite/lint and SQLModel backend tests remain GitHub CI gates because the local worktree has no installed frontend dependencies and does not provide the full locked backend test environment.
