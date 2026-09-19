# ClientFlow V2 performance and repository audit — 2026-09-19

## Scope

Canonical baseline: `main` source identity 1.3.23 / sequence 1224 after the
factory/customer handoff and pre-activation GUI source freeze. The audit compares
current V2 against the supplied legacy repository and focuses on measurable
runtime work, polling robustness, frontend bundle shape, source hotspots and
release risk. No Livestream, Terminal or Remote Desktop runtime implementation is
changed by this package.

## Measured findings

- The normal frontend entry is already route-split and small; canonical CI built
  31 chunks with an entry around 30 kB (about 9.7 kB gzip). Large HLS, Terminal
  and MUI chunks are lazy/vendor chunks rather than proof of a monolithic initial
  page load.
- Legacy `/chrome-status` primarily read the Client row. V2 additionally projects
  canonical Status/Display/System authorities. Before this package, the guarded
  performance tests documented 6 SELECTs for `/clients/` and 6 SELECTs for the
  one-second `/chrome-status` hot poll.
- V2 also added a separate `/presence` request every 5 seconds on the detail
  page, although `/chrome-status` already had to evaluate the same canonical
  presence to project its response.
- The separate presence interval used an async `setInterval` without an in-flight
  guard. Additional deployment, Ubuntu-update and local-management interval
  pollers had the same overlap risk. Existing diagnostics/configuration polling
  already used the safer in-flight-guard pattern.

## Changes in this package

1. Presence status and its credential are read in one joined database query.
   Canonical credential/revocation checks remain unchanged.
2. `/clients/` projection budget is reduced from 6 to 5 SELECTs, constant in N.
3. `/chrome-status` projection budget is reduced from 6 to 5 SELECTs and carries
   the already-evaluated canonical presence payload.
4. The detail page removes the duplicate 5-second presence HTTP poll. It consumes
   canonical presence from the existing sequential `/chrome-status` loop and
   still fails closed when that hot poll cannot obtain a fresh server response.
5. Async interval pollers for ClientFlow deployments, Ubuntu update and local
   management now have explicit in-flight guards.
6. `/api/clients*` responses expose only a dataminimized `Server-Timing: app`
   duration. This makes actual backend processing time observable in browser
   DevTools without exposing SQL, hostnames, query text or credentials.

For the detail hot path, the known SELECT budget over five seconds falls from
`5 * 6 + 3 = 33` to `5 * 5 = 25`, about 24% fewer database round-trips. This is a
query-work reduction, not a claim of 24% lower end-user latency; actual production
latency must be measured after deployment.

## Source-size audit

Largest current implementation files after this package:

- `frontend/src/pages/clientdetailspage/ClientDetailsInfoSection.jsx`: ~3.4k lines
- `backend/service1/routers/clients.py`: ~3.0k lines
- `frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx`: ~2.8k lines
- `frontend/src/pages/ClientInfoPage.jsx`: ~2.2k lines
- `frontend/src/pages/adminpages/UserAdministration.jsx`: ~1.8k lines
- `frontend/src/pages/calendarpage/CalendarPage.jsx`: ~1.8k lines
- `frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx`: ~1.6k lines
- `backend/service1/routers/remote_desktop_v2.py`: ~1.5k lines
- `frontend/src/api/api.js`: ~1.3k lines

These are maintainability hotspots, but line count alone is not evidence of
runtime slowness. They should be split later along existing domain boundaries,
with behavior held constant and CI green, rather than mixed into this hot-path
performance change.

## Database/index conclusion

The canonical domain tables already carry relevant indexes for client/domain,
status freshness, active credentials and command lookups. This audit does not add
speculative indexes. Production-like PostgreSQL query plans should be inspected
with `EXPLAIN (ANALYZE, BUFFERS)` before any further index change.

## Next measurement gate

After this package is merged and deployed to a test/production-like backend:

- compare `Server-Timing: app` for `/api/clients/`, `/chrome-status` and
  `/presence` before/after where historical traces are available;
- verify Render-to-PostgreSQL network locality/RTT rather than assuming region;
- capture PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` for the remaining hot queries;
- use React Profiler on the client list and detail page before deciding on any
  memoization or component split.

No file deletion is required by this package.
