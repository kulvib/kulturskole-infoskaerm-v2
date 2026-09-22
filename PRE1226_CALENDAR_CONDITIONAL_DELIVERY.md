# Pre-1226 Calendar conditional delivery

## Status

Branch: `perf/pre1226-calendar-conditional-delivery`

Release 1.3.25 / seq 1226 remains paused. This package is built on the fresh
merged 1.3.24 / seq 1225 main and does not alter release identity or polling
cadence.

## Root cause

The Display Calendar agent polls every 15 seconds. Before this package every
successful poll selected and transferred the full `CalendarMarking.markings`
JSONB for both current and next season, even when nothing had changed.

An HTTP ETag alone would not solve the database cost: if the ETag were derived
from `markings`, PostgreSQL would still have to read the large JSONB on every
poll. The cache validator therefore needs lightweight durable row metadata.

## Change

Step 56A adds `CalendarMarking.updated_at`.

- Existing rows are backfilled once by Alembic.
- New rows receive `utcnow()` from the SQLAlchemy model.
- ORM updates receive a fresh value through `Column(..., onupdate=utcnow)`.
- The repo audit found all current CalendarMarking write paths assigning a new
  `markings` value through SQLAlchemy ORM; there are no in-place markings
  mutations or raw SQL CalendarMarking UPDATE paths in the current source.

The delivery route now supports `If-None-Match`:

1. First request after Calendar service start remains a normal complete fetch.
2. The backend returns a strong ETag derived from current/next season name,
   row id and `updated_at`.
3. Subsequent 15-second polls send that ETag.
4. The backend authorizes the Display credential exactly as before, then reads
   only `id`, `season`, and `updated_at` from CalendarMarking.
5. If unchanged, it returns HTTP 304 and does not select `markings` JSONB.
6. If changed, it performs the complete two-season fetch, validates the full
   calendar exactly as before, and returns HTTP 200 with the new ETag.

Season names are part of the ETag input, so the validator automatically changes
when `current_and_next_seasons()` rolls forward even if no edit occurs at the
boundary.

## Functional invariants

Unchanged:

- 15 second Calendar fetch cadence.
- 30 second local wall-clock evaluation cadence.
- complete current+next season requirement.
- canonical content SHA-256 revision inside the Calendar payload.
- Display-domain self-only authorization.
- local validated cache and offline behavior.
- 409 fail-safe for incomplete backend calendars.
- manual override / boot grace / wake reboot semantics.

A 304 without an existing local validated plan fails closed.

## Database / Neon effect

The SELECT count for an unchanged Calendar request stays intentionally bounded
at two statements: one credential+Client authorization SELECT and one Calendar
metadata SELECT. The important reduction is data volume and JSONB materialization:
the two full `markings` JSONB documents are no longer selected every 15 seconds
when unchanged.

On a change, the conditional request temporarily costs one additional metadata
SELECT before the normal full Calendar SELECT. Calendar edits are expected to
be rare relative to idle polling, so this trades a rare small query for removal
of continuous large JSONB reads.

No authorization caching or stale cross-request state is introduced.

## Migration

New head: `20260922_56a_calendar_delivery_revision`

Predecessor: `20260908_55a_enroll_binding`

The reviewed baseline/reconciliation chain is explicitly advanced through 56A;
55A remains the required direct predecessor.

## Local validation

- `python -m py_compile` for modified Python sources: PASS
- Alembic graph: one head, 56A -> 55A: PASS
- schema contract fingerprint: PASS
- `scripts/tests`: 286 passed
- relevant backend schema/calendar source contracts: 99 passed
- focused conditional Calendar tests included in the above: PASS

The executable SQLModel database-cost test is included for GitHub CI and is not
run locally because this sandbox does not contain the repo's pinned SQLModel
backend dependency environment.
