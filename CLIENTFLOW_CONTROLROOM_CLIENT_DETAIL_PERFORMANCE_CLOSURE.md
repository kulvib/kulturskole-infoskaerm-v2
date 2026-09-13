# ClientFlow Controlroom client-detail read performance closure

Branch target: `fix/controlroom-client-detail-read-performance`

Canonical base source: `753917f52c671686350851de5a982b6c7e683e88`
Canonical base CI: `#679 / run 34777686463` -> success.
Source identity remains: ClientFlow `1.3.21 / seq 1222`.
Runtime catalog remains deliberately on `1.3.20 / seq 1221`.
Releaseflow remains paused; this source batch does not build, publish, approve or promote 1222.

## Root cause

The Client Details page intentionally preserves the deployed legacy 1.1.19
`/clients/{id}/chrome-status` polling cadence of one request per second. The
polling interval is therefore not the regression.

V2 expanded that compatibility endpoint with canonical Status, Display and
System projections. Before this closure, each normal approved-client poll read:

1. the Client row;
2. canonical Status/Display/System domain-status rows;
3. their credentials;
4. Display desired configuration;
5. the latest Display status row again;
6. the active Display control command;
7. the latest reboot/shutdown System command;
8. the latest OS-update System command;
9. the latest local-management System command.

For an ordinary approved client with domain credentials this is **9 SELECTs per
one-second poll**. The extra work is backend read amplification introduced by
canonical compatibility projections, not a larger initial frontend bundle or a
new polling timer.

The separately polled `/clients/{id}/presence` endpoint remains intentionally
separate. Global liveness is a canonical Status-domain contract and must not be
reconstructed from the legacy-shaped chrome-status response merely to save a
request.

## Implementation

The endpoint now uses the same CI-approved batch primitives introduced for the
client-list performance closure:

- `load_client_presences_with_status_rows(session, [client])` evaluates
  presence and exposes the already-read Display status row;
- `display_read_projections(...)` reuses that row and performs only the desired
  configuration and active Display-command reads;
- `load_latest_system_projection_commands(session, [client_id])` performs one
  bounded window query for the latest power, OS-update and local-management
  commands.

The existing projection application functions are unchanged. This means field
mapping, pending-state semantics, stale/revoked status-row handling, power
lifecycle attribution and API response shape continue to use the same canonical
projection code as before.

## Resulting query bound

For an ordinary approved client with credentials, one chrome-status poll now
performs:

1. Client lookup;
2. shared domain-status batch;
3. shared credential batch;
4. Display desired-configuration batch;
5. active Display-command batch;
6. latest System projection-command window query.

Total: **6 SELECTs per poll**, down from 9.

The frontend polling cadence remains exactly one second. No cache, debounce,
stale-response shortcut or hidden behavioral change is introduced.

## Bundle/load audit context

The preceding canonical frontend build demonstrated that bundle size is not the
root cause for this path: route splitting remains active and heavy HLS/Terminal
chunks are lazy-loaded. This closure therefore fixes the measured API/database
work rather than changing bundle strategy or frontend behavior.

Node's `MODULE_TYPELESS_PACKAGE_JSON` warning seen in CI concerns Node test-time
module reparsing for individual source files. It is not evidence of a browser
production-bundle bottleneck and is not mixed into this read-path fix.

## Best-practice basis

The implementation follows SQLAlchemy's documented Select-IN/batch-loading
principle for avoiding N+1-style repeated reads. Latest-per-group System
commands continue to use the existing `row_number() OVER (...)` database-side
ranking, keeping historical command loading bounded.

No cache is added and no polling interval is increased. The performance issue
is addressed at the measured query path while preserving product behavior.

## Regression gates

`backend/tests/test_client_list_projection_performance.py` now also exercises
the real `get_chrome_status()` function against databases containing 1, 10, 50
and 100 clients. It requires exactly **6 SELECTs in every case** and checks
representative Display/System projection values.

`backend/tests/test_clientflow_display_browser_request_projection.py` continues
to verify browser-request projection behavior while mocking the new batch
interfaces rather than retired per-object internals.

`backend/tests/test_client_liveness_52a_source.py` locks the endpoint to the
batch presence/Display/System loaders and explicitly rejects a regression back
to `load_client_presence(session, client)` on the one-second path.

Local dependency-independent evidence before GitHub CI:

- `scripts/tests`: 226 passed;
- relevant liveness/Display source contracts: 22 passed;
- Python compileall for touched modules/tests: PASS.

The dynamic SQLModel SELECT-count test requires the repository's hash-locked
backend dependencies and is therefore an authoritative GitHub-CI gate. It must
not be reported green until canonical CI executes it.

## Frozen domains / non-goals

No implementation change is made to:

- Livestream;
- Terminal;
- Remote Desktop;
- frontend polling intervals;
- frontend API schema or rendering behavior;
- canonical presence semantics;
- release identity/catalog authority;
- immutable published releases.

After merge and full canonical green CI, use a fresh `main` for the final
1.3.21/1222 source-freeze audit before releaseflow is explicitly resumed.
