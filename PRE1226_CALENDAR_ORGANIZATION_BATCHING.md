# Pre-1226 calendar / organization batching

Branch: `perf/pre1226-calendar-organization-batching`

Release 1.3.25 / sequence 1226 remains paused. This package does not change
release identity, schema, migrations, polling cadence, authorization rules or
calendar semantics.

## Repo-proven root causes

### `POST /calendar/marked-days`

Before this package, the endpoint executed one `Client` read per requested
client and one `CalendarMarking` read per requested client. For N clients that
was up to 2N SELECTs before writes.

The endpoint now:

1. loads only `(Client.id, Client.organization_id)` for all requested clients in
   one query;
2. preserves the original request-order 404/403 checks in Python;
3. validates complete calendars exactly as before;
4. loads all existing `CalendarMarking` rows for the season in one query; and
5. writes each unique client once. Duplicate client IDs are therefore
   idempotent instead of repeating identical work.

For 100 unique clients the pre-write read shape changes from up to 200 SELECTs
to 2 SELECTs.

### Organization `apply-season-times`

Before this package, approved clients were loaded as full `Client` ORM rows and
each client then caused an individual `CalendarMarking` SELECT.

The endpoint now projects only `Client.id` and batch-loads all existing
calendars for `(season, client_ids)` once. The safe standard-time merge logic,
manual-day preservation, counters, audit event and transaction boundary are
unchanged.

The endpoint's calendar/client read count is now constant with client count.

### Organization `replace-season-calendars`

The same N+1 pattern existed in the destructive replace flow. It now projects
only `Client.id` and batch-loads existing calendars once. The `OVERSKRIV`
confirmation gate, critical audit event, replacement semantics and single
transaction are unchanged.

### `/organizations/season-summary`

The old implementation loaded full rows from Organization, Client,
OrganizationSeasonTimes and CalendarMarking. In particular, it loaded the full
`CalendarMarking.markings` season JSON even though the response only needs a
season and organization mapping.

The endpoint now uses three bounded projections:

- `(Organization.id, Organization.name)`;
- `(OrganizationSeasonTimes.season, organization_id)`; and
- `(CalendarMarking.season, Client.organization_id)` through a join.

No calendar JSON is loaded for the summary. Organization access filtering and
the response shape are unchanged.

## Deliberately not changed

- database schema or indexes;
- current/next season rules;
- complete-calendar validation;
- authorization / organization boundaries;
- audit logging;
- commit/rollback boundaries;
- display-agent calendar polling;
- frontend polling;
- release version or sequence.

Those remain separate pre-1226 workstreams so a performance change cannot hide
a functional or release-state change.
