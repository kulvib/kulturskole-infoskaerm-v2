# ClientFlow 1.3.25 / sequence 1226 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the full
pre-1226 parity, database-cost and runtime-transport review was merged to
canonical `main`.

Canonical authority before this identity transition:

- source/build identity: `1.3.24 / 1225`;
- runtime catalog: `clientflow-1.3.24-seq-1225`;
- catalog sequence: `1225`;
- database migration head: `20260922_56a_calendar_rev`;
- minimum Ubuntu LTS: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`.

The exact Git commit SHA of the uploaded fresh-main archive is not embedded in
the archive itself. The authoritative 40-character source-freeze SHA must be
recorded from GitHub after this identity transition is merged and canonical
push CI is green.

Staged source/build identity after this change:

- version: `1.3.25`;
- release sequence: `1226`;
- candidate release id: `clientflow-1.3.25-seq-1226`.

This document is source/build identity only. It is not approval, publication,
or catalog-promotion authority.

## Included pre-1226 closures

The 1.3.25/1226 source includes the already merged canonical closures completed
while 1226 was deliberately paused:

- local GUI parity against the pinned legacy 1.1.19 runtime, including legacy
  six-row kiosk structure, system-information structure, ellipsis behaviour,
  calendar proportions, uptime/resolution formatting and no administrator
  switch;
- agent hot-path database-cost reduction with bounded authentication/status
  reads and shared per-request command reconciliation;
- calendar/organization batching that removes per-client N+1 read patterns;
- Control Room adaptive polling and narrowed list transport while retaining
  fast polling during active user-visible actions;
- Client Details hot-state deduplication and bounded canonical presence reads;
- Display/System heartbeat + command-claim request consolidation without
  changing 5-second command latency or 15-second status freshness;
- update-plane idle request consolidation with explicit backward-compatible
  fallback and unchanged update-detection cadence;
- conditional calendar delivery using ETag/If-None-Match and migration 56A so
  unchanged 15-second polls avoid loading full calendar JSONB.

Livestream, Terminal and Remote Desktop implementation domains remain frozen.

## Release-gate separation

The runtime catalog intentionally remains on the last approved, published and
promoted selector authority:

- `catalog_sequence = 1225`;
- `latest_stable = 1.3.24`;
- `default_install_version = 1.3.24`;
- selected release = `clientflow-1.3.24-seq-1225`.

The source/build identity therefore leads the catalog by exactly one sequence.
The catalog must not select 1.3.25/1226 until the exact candidate has passed
runtime-input transport verification, reproducible build, Ubuntu 26.04
executable-candidate verification, manual approval, immutable publication and
independent store re-read.

## Next gates

After this source-freeze change is merged and canonical push CI is green:

1. record the exact resulting 40-character source-freeze commit SHA;
2. prepare/verify the locked runtime-input transport for sequence 1226;
3. run the canonical reproducible release build for that exact source SHA;
4. require byte-identical independent outputs and Ubuntu 26.04 executable-candidate PASS;
5. manually approve the exact reproducible candidate;
6. publish approved bytes immutably and independently re-read size/SHA-256;
7. only then promote the separate runtime catalog to 1.3.25/1226;
8. regenerate the canonical preparation USB from promoted main;
9. run clean physical Ubuntu 26.04 fresh-install acceptance from phase 0.
