# Pre-1226 detail hot-state database deduplication

Branch: `perf/pre1226-detail-hotstate-db-dedup`

Release 1.3.25 / sequence 1226 remains paused. This package changes no release identity, schema, migration, agent cadence, command latency, authorization rule, or UI action semantics.

## Repo-proven root cause

The fresh main already had adaptive 1s/5s `/chrome-status` polling, but Client Details still had two parallel full-client polling loops:

- Configuration: `GET /clients/{id}/` every 15 seconds while the tab was open.
- Diagnostics: `GET /clients/{id}/` every 10 seconds while the tab was open.

Those full reads repeated canonical Status/Display/System projection work that the parent `/chrome-status` request already performed. In addition, `/chrome-status` itself first selected `Client` and then separately selected shared-domain status/credential evidence.

The old full-detail read path also used one-by-one Display/System projection helpers. From the repository code this yields the following SQL round-trip model for a normal full read: 1 Client + 1 shared presence + 3 Display + 3 System = 8 SELECTs. The hot `/chrome-status` path was CI-locked at 5 SELECTs.

## Changes

1. `load_client_with_presence_rows()` loads the Client row and shared Status/Display/System evidence in one joined SELECT. Presence still evaluates the exact same approved/deleted/credential-revocation/freshness rules on every request; there is no cross-request cache.
2. The joined credential entity is `load_only(...)` projected to `id`, `client_id`, `domain`, and `revoked_at`; `secret_hash` is not selected for ordinary presence/detail reads.
3. `/clients/{id}/chrome-status` reuses that joined base evidence and remains otherwise on the existing two Display batch queries + one System command projection query. Executable CI budget: 4 SELECTs, constant with 1/10/50/100 seeded clients.
4. `GET /clients/{id}/` uses the same bounded single-client projection. Executable CI budget: 4 SELECTs, constant with 1/10/50/100 seeded clients.
5. `/clients/{id}/presence` reuses the joined base evidence, reducing its repository query model from 2 SELECTs to 1.
6. Configuration and Diagnostics fields that are already present on the loaded Client/canonical projection are transported on `/chrome-status` and merged into `liveClient`.
7. The 10-second Diagnostics and 15-second Configuration full-client intervals are removed. Manual full refresh remains available.
8. Adaptive cadence is unchanged: 1 second during active transitions, 5 seconds while stable, and DB-backed hot polling pauses while the browser page is hidden.

## Expected database impact

All figures below are SQL round-trip models from repository code; Neon production billing/compute impact must be measured separately.

- Stable detail hot read: 5 -> 4 SELECTs/request (20% reduction).
- Stable detail page: 12 hot requests/minute, therefore 60 -> 48 SELECTs/minute.
- Active detail action: 60 hot requests/minute, therefore 300 -> 240 SELECTs/minute while the 1-second responsiveness is retained.
- Configuration tab before: 60 hot SELECTs/minute + about 32 full-read SELECTs/minute = about 92. After: about 48. Approx. 48% reduction.
- Diagnostics tab before: 60 hot SELECTs/minute + about 48 full-read SELECTs/minute = about 108. After: about 48. Approx. 56% reduction.
- Initial/manual full detail read: repository model 8 -> executable CI target 4 SELECTs.

The hot response becomes slightly wider because it carries the non-secret values that replace the removed periodic full-client responses. This is intentional: those values come from rows/projections already loaded for the hot request, so the trade removes whole database requests rather than adding database work. No token, credential secret, password, or encrypted command payload is exposed.

## Functional invariants

- Canonical Status-domain presence remains the only global liveness authority.
- Credential revocation is checked from the database on every presence/hot request.
- Display desired/observed state remains Display-domain authority.
- System power/update/local-management state remains System-domain authority.
- 1-second action responsiveness remains unchanged.
- Configuration form dirty-state protection remains unchanged; live snapshots must not overwrite in-progress edits.
- Explicit manual refresh remains a full re-read.
- No migration or index is introduced.

## External best-practice boundary

The code changes above are justified by repository evidence. PostgreSQL guidance is used only for the later production/staging measurement phase: run `ANALYZE` and inspect real query plans/index use with `EXPLAIN` before introducing additional indexes. Neon pricing is usage-based primarily around compute/storage rather than a fixed fee per SQL statement; reducing redundant round-trips is still useful because it reduces database work and active compute pressure.
