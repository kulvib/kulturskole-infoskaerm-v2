# Pre-1226 Control Room adaptive polling + payload closure

Branch target: `perf/pre1226-controlroom-adaptive-polling-payload`

Source identity remains ClientFlow `1.3.24 / seq 1225`. Release `1.3.25 / seq 1226` remains paused.

## Repo-proven root cause

After the merged hot-path database-cost work, both the Control Room list and the
`/clients/{id}/chrome-status` detail hot read are bounded at 5 SELECT statements
per request. The remaining always-on cost is therefore request multiplication:

- Control Room list: every 2 seconds = 30 requests/minute = 150 SELECTs/minute
  for one visible stable list.
- Client detail: every 1 second = 60 requests/minute = 300 SELECTs/minute for
  one visible stable detail page.

The list additionally used the very broad `ClientRead` response schema even
though `ClientInfoPage` renders only a small subset. `ClientRead` has 132
annotated top-level fields including inherited `ClientBase`; the new
`ClientControlRoomListRead` has 20. This is a response-width optimization, not
an assertion that PostgreSQL row width has been reduced: the canonical list
projection still reads the same Client rows and keeps the same 5-query bound.

## Implementation

### Control Room list

- new `GET /api/clients/control-room-summary` transport;
- reuses the existing authorization and `_prepare_clients_read()` canonical
  Status/Display/System projection path;
- response model exposes only fields needed for list rendering/comparison and
  adaptive-poll state;
- stable visible list: 5-second polling;
- pending/unapproved or active command/update state: historical 2-second polling;
- hidden page: no DB-backed list poll;
- focus/visibility retains immediate refresh behavior.

A stable sleeping/offline/error client does **not** force perpetual fast
polling. Fast cadence is tied to actual pending/transition evidence.

### Client detail

- stable `/chrome-status`: 5-second polling;
- active kiosk/System/update/local-management transition: 1-second polling;
- starting a user action immediately opens a bounded 1-second fast-poll window
  and wakes a sleeping idle poll;
- focus/visibility wakes the poll immediately;
- hidden page performs no DB-backed hot read;
- transient poll failure keeps the previous fail-closed presence behavior and
  retries at the 1-second cadence.

No command cadence, heartbeat cadence, presence timeout, domain authority,
authorization rule or API mutation semantics are changed.

## Expected stable-page request reduction

Using the CI-locked 5-SELECT budget per request:

- list: 150 -> 60 SELECTs/minute (60% reduction);
- detail: 300 -> 60 SELECTs/minute (80% reduction);
- one stable visible list + one stable detail page: 450 -> 120 SELECTs/minute
  (73.3% reduction).

Active user operations retain the old fast cadence, so action confirmation
latency is not traded away for the idle-state saving.

## Best-practice distinction

Repo evidence proves the current request cadence, query budget and page state
contracts. External browser guidance supports stopping unnecessary work on
hidden pages, while React effect guidance supports explicit setup/cleanup for
polling side effects. Those external principles inform the implementation, but
they do not substitute for the repo-specific regression gates.

## Gates

Local dependency-independent evidence:

- scripts/client suite: 278 passed;
- targeted frontend polling/request-budget contracts: 9 passed;
- backend source payload contract: 1 passed;
- Python `py_compile` for changed backend modules/tests: PASS.

The executable SQLModel query-count extension for the new summary route is
included but requires the repository's backend dependency environment. GitHub
CI remains the authoritative gate.
