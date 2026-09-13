# ClientFlow Controlroom client-list read performance closure

Branch target: `fix/controlroom-client-list-read-performance`

Canonical base source: `19f64ba553ace59a79138a9bb339e77442649fa6`
Source identity remains: ClientFlow `1.3.21 / seq 1222`.
Runtime catalog remains deliberately on `1.3.20 / seq 1221`.
Releaseflow remains paused; this source batch does not build, publish, approve or promote 1222.

## Root cause

The deployed V2 client-list read path attached canonical Display and System
compatibility projections after loading the client rows. Shared Status/Display/System
presence was already batched, but every client then executed six additional reads:

1. Display desired configuration;
2. Display status;
3. active Display control command;
4. latest reboot/shutdown System command;
5. latest OS-update System command;
6. latest local-management System command.

Therefore `/clients/` had a deterministic read amplification of:

`1 client query + 1 status batch + optional 1 credential batch + 6 * N clients`

For ordinary approved clients with domain credentials this is `3 + 6N` SELECTs:

- 1 client: 9 SELECTs;
- 10 clients: 69 SELECTs;
- 50 clients: 309 SELECTs;
- 100 clients: 609 SELECTs.

The legacy 1.1.19 list endpoint selected the clients once and calculated its
legacy liveness/status fields from columns already present on each Client row.
The V2 overhead is therefore attributable to the canonical read projections,
not to a larger frontend source tree or a newly introduced list polling timer.

A deeper audit corrected the earlier preliminary estimate of `5N`: Display also
queries the active Display command, so the factual pre-fix amplification is `6N`.

## Implementation

### Presence/status reuse

`client_presence.py` now exposes the already-loaded raw domain status rows next
to evaluated presence. Display projection can therefore reuse the exact
`ClientDomainStatus(domain="display")` row instead of selecting it again per
client. The raw row is deliberately retained even when presence evaluates
offline, preserving existing projection semantics for stale/revoked evidence.

### Display batching

The list path performs exactly two Display reads for the whole client set:

- one `IN (...)` query for durable desired configurations;
- one bounded active-command query for queued/claimed, unexpired Display control
  commands.

The active-command ordering remains the existing `requested_at ASC, id ASC`
contract, and `apply_configuration` remains excluded from the legacy pending
Chrome/Display action projection.

### System batching

Power, OS-update and local-management projections retain their existing pure
projection semantics but can now consume an already selected `ClientCommand`.

A single SQL window query selects at most the newest command in each of the
three disjoint projection groups per client. It preserves the existing ordering
`requested_at DESC, id DESC` and uses `row_number()` so historical command rows
are not loaded into application memory merely to remove N+1 round trips.

### Resulting query bound

For an ordinary list with credentials the endpoint now performs:

1. client list;
2. shared domain status batch;
3. shared credential batch;
4. Display desired configuration batch;
5. active Display command batch;
6. latest System projection command window query.

Total: **6 SELECTs independent of N**.

This is a reduction from 69 -> 6 SELECTs at 10 clients, 309 -> 6 at 50 clients,
and 609 -> 6 at 100 clients. The API schema, sorting, permissions, projection
values and frontend polling cadence are unchanged.

## Best-practice basis

The implementation follows SQLAlchemy's documented select-IN/batch-loading
principle for avoiding N+1 access patterns. Latest-per-group command selection
uses a SQL window function (`row_number() OVER (...)`) so the database performs
the bounded ranking rather than returning an unbounded command history to
Python.

No cache was added and no polling interval was increased. The performance issue
is fixed at its measured read-path root cause rather than hidden by making the
Controlroom less responsive.

## Regression gates

`backend/tests/test_client_list_projection_performance.py` adds executable
SQLite/SQLModel contracts that:

- measure actual SELECT statements on the real `/clients/` function at 1, 10,
  50 and 100 clients and require exactly 6 each time;
- seed older/newer commands in all three System projection groups;
- compare the new batched projection against the unchanged single-client
  projection field-for-field.

`backend/tests/test_client_liveness_52a_source.py` is updated only to describe
the new presence+status batch contract.

Local environment evidence before GitHub CI:

- `scripts/tests`: 226 passed;
- relevant liveness/Display/System source contracts: 25 passed;
- `python -m compileall backend scripts`: PASS.

The new SQLModel query-count test requires the repository's hash-locked backend
dependencies and is therefore an authoritative GitHub-CI gate. It must not be
reported green until canonical CI executes it.

## Frozen domains / non-goals

No implementation change is made to:

- Livestream;
- Terminal;
- Remote Desktop;
- frontend polling intervals;
- frontend behavior or API schema;
- release identity/catalog authority;
- immutable published releases.

After merge and full canonical green CI, use a fresh `main` as the next source
of truth. Releaseflow remains paused until the broader 1.3.21/1222 source freeze
and release procedure are explicitly resumed.
