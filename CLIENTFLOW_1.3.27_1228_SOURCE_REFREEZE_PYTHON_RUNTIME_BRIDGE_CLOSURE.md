# ClientFlow 1.3.27 / sequence 1228 — Python-runtime bridge source re-freeze closure

> **SUPERSEDED BEFORE FINAL BUILD:** This source boundary is preserved as
> historical bridge evidence. Subsequent audited source changes were re-frozen
> before candidate approval, publication or catalog promotion. Current source
> authority is `CLIENTFLOW_1.3.27_1228_POST_MAINTENANCE_FINAL_SOURCE_REFREEZE_CLOSURE.md`.

Date: 2026-09-28

## Status

This document supersedes the **initial 1.3.27/1228 source-freeze boundary** in
`CLIENTFLOW_1.3.27_1228_SOURCE_FREEZE_CLOSURE.md`.

The staged release identity remains `1.3.27 / 1228`. No sequence-1228 runtime
input transport, reproducible release build, approval, immutable publication or
catalog promotion crossed an artifact-authority boundary before the Python 3.13
patch-compatibility bridge was merged.

Canonical pre-refreeze main:

- commit: `d3d598aa5f51a36d87992d7635ea504e6440f881`;
- canonical push CI: `#1047` / run `36474336723` / completed success;
- staged source/build identity: `1.3.27 / 1228`;
- runtime catalog: `1.3.26 / 1227`;
- active runtime Python: `3.13.14`.

The exact post-merge re-freeze SHA is deliberately not embedded in this source.
It must be taken from GitHub after this re-freeze package is merged to canonical
`main` and the resulting push CI is green.

## Why the same staged identity is retained

`1.3.27/1228` has not crossed an artifact-authority boundary. Therefore the
bridge can be re-frozen under the same staged identity without creating a
sequence gap or representing unpublished bytes as a release. The source
sequence still leads the promoted catalog by exactly one:

- source release sequence: `1228`;
- catalog sequence: `1227`;
- catalog latest/default: `1.3.26`;
- selected release: `clientflow-1.3.26-seq-1227`.

## Bridge included in the re-frozen candidate

The re-frozen 1.3.27/1228 candidate intentionally remains on Python `3.13.14`
so the currently promoted 1.3.26/1227 updater can consume it using its existing
exact-3.13.14 validation path.

The bridge changes only the incoming-release compatibility boundary for a later
Python 3.13 maintenance patch:

- Python 3.13 maintenance-patch manifests from patch 14 onward are accepted;
- major/minor drift and unsupported/pre-3.13.14 values remain fail-closed;
- Python runtime TAR validation binds the archive root to the exact
  manifest-declared runtime patch;
- runtime preparation verifies the exact executed bundled interpreter version;
- release-ready verification binds the prepared runtime value to the exact
  manifest-declared patch.

The previously generated Python 3.13.15 runtime candidate from workflow run
`36471992789` remains evidence only. It is not runtime authority for 1.3.27/1228
and is not consumed by this re-freeze.

## Fresh-main re-freeze evidence

PASS:

- canonical pre-refreeze `main` is `d3d598aa5f51a36d87992d7635ea504e6440f881`;
- canonical push CI `#1047` / run `36474336723` completed successfully;
- `client/VERSION` remains `1.3.27`;
- `release_sequence` remains `1228`;
- active runtime Python remains `3.13.14`;
- promoted runtime catalog remains `1.3.26 / 1227`;
- source sequence remains exactly one ahead of the promoted catalog;
- no runtime lock, runtime-input bytes, catalog selector or release identity is
  changed by this source re-freeze.

## Authority boundary

This re-freeze is source/build authority only. It is not artifact approval,
publication or catalog-promotion authority.

Until this package is merged and the new canonical re-freeze SHA has green push
CI, the following remain forbidden:

- sequence-1228 runtime-input transport;
- reproducible release build for 1.3.27/1228;
- candidate approval;
- immutable publication;
- catalog promotion to 1.3.27/1228.

## Refreeze-safe runtime-input transport identity

A runtime-input transport is transport evidence, not release authority, but it must still be unambiguous about the source authority it was prepared for. Sequence-only transport tags cannot safely represent more than one source freeze of the same staged release sequence. The canonical transport workflow therefore uses a no-replace tag and asset name qualified by the full 40-character `expected_source_sha`. Any older sequence-1228 transport remains preserved as historical evidence and must not be deleted, overwritten or reused for a later re-freeze SHA.

Only the transport URL and SHA-256 emitted for the exact final green re-freeze SHA may feed the reproducible release build.

## Next canonical gates

After merge and green canonical push CI:

1. record the exact resulting 40-character re-freeze `main` SHA;
2. run canonical runtime-input transport for sequence 1228 from that exact SHA;
3. run the reproducible 1.3.27/1228 release build from the exact same source
   authority and locked runtime input;
4. require byte-identical independent build outputs and the Ubuntu 26.04
   executable-candidate gate to pass;
5. manually approve that exact candidate;
6. publish the approved bytes immutably and independently re-read size/SHA-256;
7. separately promote the runtime catalog to 1.3.27/1228;
8. verify the promoted 1.3.26 -> 1.3.27 bridge update path before staging a
   later release that changes the active runtime to Python 3.13.15.
