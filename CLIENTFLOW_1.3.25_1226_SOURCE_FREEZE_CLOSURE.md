# ClientFlow 1.3.25 / sequence 1226 — final pre-release source-freeze closure

## Scope

This is the final source-freeze gate after the pre-1226 functional-parity,
local-GUI, database-cost and production Neon review. It stages the complete
merged source as ClientFlow 1.3.25 / sequence 1226 while deliberately leaving
the runtime selector on the already approved/published/promoted 1.3.24/1225
release until the immutable 1226 candidate has crossed every release gate.

Canonical pre-freeze source was the fresh `main` archive supplied on
2026-09-22 after all calendar conditional-delivery CI fixes were green and
merged. The archive contains no `.git` metadata, so no source commit SHA is
guessed or self-embedded here.

## Frozen candidate identity

- `client/VERSION = 1.3.25`;
- `release_sequence = 1226`;
- candidate release id: `clientflow-1.3.25-seq-1226`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`;
- database migration head: `20260922_56a_calendar_rev`.

## Catalog boundary

This freeze does not publish or promote the candidate. The runtime catalog
remains byte-for-byte on:

- catalog sequence `1225`;
- latest/default version `1.3.24`;
- selected release `clientflow-1.3.24-seq-1225`.

Regression contracts require source sequence 1226 to lead catalog sequence
1225 by exactly one until the new immutable approved bundle exists and has been
independently verified.

## Functional and GUI closure

The frozen source retains the pinned legacy 1.1.19 functional inventory gate
and the completed GUI parity work. The local V2 GUI preserves the legacy main
structure while retaining V2 security boundaries, including no exposed
administrator-switch path. No forgotten entire legacy functional domain was
identified during the pre-1226 parity review.

## Database / Neon closure

The frozen source includes the merged database-cost packages for agent hot
paths, organization/calendar batching, adaptive Control Room polling, detail
hot-state deduplication, shared-agent request consolidation, update-plane idle
request consolidation and calendar conditional delivery.

Read-only production inspection of `display-planiq` / production on 2026-09-22
found no release blocker:

- migration head was `20260922_56a_calendar_rev`;
- production contained two current clients at inspection time;
- no query had been running longer than five minutes;
- no current database locks were reported;
- relevant tables were small (`client` about 312 kB, `calendarmarking` about
  152 kB at inspection time);
- cumulative PostgreSQL shared-buffer statistics showed 3,609,211 block hits
  versus 1,028 block reads and no temporary-file bytes;
- estimated bloat was small in absolute terms (largest reported waste about
  248 kB on `client`);
- autovacuum diagnostics reported no table currently expected to autovacuum.

`pg_stat_statements` and the Neon extension were not installed solely for this
freeze audit. Therefore `calls`/`outliers` and Neon LFC/working-set metrics are
explicitly deferred observability items, not silently inferred. No production
extension or compute setting is changed by this source freeze.

High historical sequential-scan counts remain concentrated in frozen
Livestream/activity tables. Their current table sizes and the two-client
production workload do not justify opening the frozen Livestream architecture
or deleting indexes immediately before release.

## Frozen implementation domains

Livestream, Terminal and Remote Desktop implementation domains remain frozen.
No additional pre-1226 runtime optimization is introduced by this source-freeze
package.

## Source-freeze decision

**PASS for source freeze**, subject to canonical GitHub CI after merge.

The next step is release mechanics, not further product/performance changes:
record exact freeze SHA, build deterministic runtime-input transport 1226,
produce reproducible candidate bytes, execute Ubuntu 26.04 candidate/physical
acceptance gates, manually approve, immutably publish/re-read, and only then
promote catalog 1226.
