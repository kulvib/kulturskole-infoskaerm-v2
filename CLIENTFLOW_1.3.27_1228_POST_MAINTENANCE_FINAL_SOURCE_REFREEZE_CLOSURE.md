# ClientFlow 1.3.27 / sequence 1228 — post-maintenance final source re-freeze closure

Date: 2026-09-30

## Status

**FINAL SOURCE RE-FREEZE PENDING MERGE + GREEN CANONICAL CI.**

This document is the current source/build authority boundary for the staged
ClientFlow `1.3.27 / 1228` candidate after the complete pre-release maintenance,
security, database-cost, Livestream and CI-runtime optimization wave.

The staged release identity remains unchanged:

- version: `1.3.27`;
- release sequence: `1228`;
- candidate release id: `clientflow-1.3.27-seq-1228`;
- minimum Ubuntu LTS: `26.04`;
- architecture: `amd64`;
- embedded runtime Python: `3.13.14`.

The promoted runtime catalog remains `1.3.26 / 1227`. The 1.3.27/1228 release
must remain on embedded Python `3.13.14` because it is the compatibility bridge
consumed by the currently promoted 1.3.26/1227 updater. The deterministic
Python `3.13.15` runtime candidate remains evidence for the first post-1228
runtime upgrade and is not release authority for 1228.

Canonical pre-refreeze main:

- commit: `cd0482434f18866a52ceddefe12f1464219d9b71`;
- canonical push CI: `#1161` / run `36734756428` / completed success;
- staged source/build identity: `1.3.27 / 1228`;
- runtime catalog: `1.3.26 / 1227`;
- embedded runtime Python: `3.13.14`.

The exact post-merge re-freeze SHA is deliberately not embedded here. It must
be taken from GitHub after this closure package is merged to canonical `main`
and the resulting push CI is green.

## Why this final re-freeze is required

The previously prepared 1.3.27/1228 source authority was explicitly reopened
before any runtime-input transport or canonical release build crossed the
artifact-authority boundary. Since then, the source changed in documented,
validated ways:

- backend and CI Python moved to `3.13.15` while the 1228 embedded runtime
  remained `3.13.14`;
- frontend build toolchain moved to Node `24.21.0` / npm `11.19.0`;
- direct dependency maintenance was completed and lockfiles regenerated;
- the PyJWT security floor was raised to `2.14.0`;
- the temporary exact `brace-expansion 1.1.21` npm-audit false-positive waiver
  was made short-lived and fail-closed;
- Livestream sweeper query-frequency waste was removed and verified in
  production with flat post-deploy hot-path query counters;
- the stale `clientflow_foundations_50a_test` Neon database was removed after
  read-only verification that it was empty, inactive and unreferenced;
- canonical CI was optimized without weakening coverage: duplicate backend test
  execution was removed, Ubuntu 26.04 host proofs were parallelized, and the
  expensive host proof is now scope-gated while the required aggregate host
  contract remains fail-closed;
- canonical post-merge CI for the current main completed successfully in about
  1 minute 43 seconds instead of the earlier multi-minute critical path.

No promoted catalog selector, release sequence, embedded runtime pin or
approved immutable release bytes are changed by this re-freeze.

## Frozen candidate identity

- source release sequence: `1228`;
- catalog sequence: `1227`;
- catalog latest/default: `1.3.26`;
- selected release: `clientflow-1.3.26-seq-1227`.

The source remains exactly one sequence ahead of the promoted catalog.

## Artifact-authority boundary

Any earlier sequence-1228 runtime-input transports or build evidence remain
historical only. They must not be deleted, overwritten or reused for this final
source authority.

Only a transport emitted by `.github/workflows/runtime-input-transport.yml` for
the exact final green post-merge `expected_source_sha` may feed the canonical
release build. The transport tag and asset remain qualified by the full source
SHA.

This closure is source/build authority only. It is not manual approval,
immutable publication or catalog-promotion authority.

## Stop rule

After this package is merged and canonical CI is green, the 1.3.27/1228 source
is frozen. Do not make further functional, dependency, formatting, CI or cleanup
changes before building 1.3.27/1228. Any source change invalidates the pending
artifact chain and requires another source re-freeze and a new
source-SHA-qualified runtime-input transport.

## Next canonical gates

1. record the exact final 40-character `main` SHA after this merge;
2. require canonical CI green for that exact SHA;
3. run `Prepare ClientFlow runtime-input transport` with that SHA as
   `expected_source_sha` while retaining embedded Python `3.13.14`;
4. record the emitted `runtime_inputs_url` and `runtime_inputs_sha256`;
5. run the canonical reproducible release build with the exact same source SHA
   and transport;
6. require byte-identical independent builds and the Ubuntu 26.04 executable
   candidate gate;
7. manually approve that exact candidate;
8. publish the approved bytes immutably and independently re-read size/SHA-256;
9. separately promote the runtime catalog to `1.3.27 / 1228`;
10. verify the promoted `1.3.26 -> 1.3.27` bridge update path before staging a
    later release that changes the embedded runtime to Python `3.13.15`.
