# ClientFlow 1.3.27 / sequence 1228 — final source re-freeze closure

Date: 2026-09-29

## Status

**SUPERSEDED BEFORE BUILD — pre-release maintenance wave (2026-09-29).**

The operator explicitly reopened the staged 1.3.27/1228 source before runtime-input transport and canonical release build in order to modernize the backend/frontend toolchains and complete dependency/cost maintenance. No artifact chain derived from this closure is release authority. A new final source re-freeze is required after the maintenance wave is complete. The ClientFlow 1.3.27/1228 embedded runtime remains Python `3.13.14` because this release is the compatibility bridge consumed by the currently promoted 1.3.26/1227 updater; the deterministic Python `3.13.15` runtime candidate is evidence for the first post-1228 runtime upgrade, not authority to bypass that bridge.

This document supersedes the previous 1.3.27/1228 Python-runtime bridge
source re-freeze as the current source/build authority boundary.

The staged release identity remains `1.3.27 / 1228`. The promoted runtime
catalog remains `1.3.26 / 1227`, and runtime Python remains `3.13.14`.

Canonical pre-final-refreeze main:

- commit: `678092b596806e0952de96163899c6bdecc0719d`;
- canonical push CI: `#1090` / run `36599288657` / confirmed green;
- staged source/build identity: `1.3.27 / 1228`;
- runtime catalog: `1.3.26 / 1227`;
- active runtime Python: `3.13.14`.

The exact post-merge final re-freeze SHA is deliberately not embedded in this
source. It must be taken from GitHub after this closure package is merged to
canonical `main` and the resulting push CI is green.

## Why a final re-freeze is required

Source changed after the earlier Python-runtime bridge re-freeze while the
release remained staged. Those changes closed documented integrity and
performance findings before any 1.3.27/1228 candidate was approved, published
or promoted:

- runtime-input transport identity was made source-SHA-qualified and no-replace,
  so older sequence-1228 transport evidence cannot be overwritten or reused for
  a later source authority;
- the administrative enrollment-token list removed its N+1 client lookup and
  now keeps database SELECT count constant as token volume grows;
- a query-budget regression contract covers 1, 10, 50 and 100 used tokens;
- an accidental repository-root `service1/` / `tests/` delivery overlay was
  removed, and source-freeze hygiene now rejects recurrence;
- the required GitHub `main` CI ruleset was enabled so the three canonical CI
  jobs are a repository-enforced merge gate rather than only a process rule.

No release identity, runtime lock, runtime catalog selector or immutable release
bytes are changed by this final source re-freeze.

## Frozen candidate identity

- version: `1.3.27`;
- release sequence: `1228`;
- candidate release id: `clientflow-1.3.27-seq-1228`;
- minimum Ubuntu LTS: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`.

The staged source sequence still leads the promoted catalog by exactly one:

- source release sequence: `1228`;
- catalog sequence: `1227`;
- catalog latest/default: `1.3.26`;
- selected release: `clientflow-1.3.26-seq-1227`.

## Artifact-authority boundary

Earlier sequence-1228 runtime-input transport artifacts, if present, remain
historical transport evidence only. They are not release authority and must not
be deleted, overwritten or reused for this final source SHA.

Only a transport emitted by `.github/workflows/runtime-input-transport.yml` for
the exact final green post-merge `expected_source_sha` may feed the canonical
release build. Its tag and asset are qualified by that full source SHA.

This closure is not candidate approval, immutable publication or catalog
promotion authority.

## Stop rule

After this closure is merged and canonical CI is green, the source is frozen.
Do not make further functional, dependency, formatting or cleanup changes before
building 1.3.27/1228. Any source change invalidates the pending artifact chain
and requires a new source re-freeze and a new source-SHA-qualified transport.

## Next canonical gates

1. record the exact final 40-character `main` SHA after this merge;
2. require canonical CI green for that exact SHA;
3. run `Prepare ClientFlow runtime-input transport` with that SHA as
   `expected_source_sha`;
4. record the emitted `runtime_inputs_url` and `runtime_inputs_sha256`;
5. run the canonical reproducible release build with the exact same source SHA
   and transport;
6. require byte-identical independent builds and the Ubuntu 26.04 executable
   candidate gate;
7. manually approve that exact candidate;
8. publish the approved bytes immutably and independently re-read size/SHA-256;
9. separately promote the runtime catalog to 1.3.27/1228;
10. verify the promoted 1.3.26 -> 1.3.27 bridge update path before staging a
    later runtime-Python upgrade.
