# ClientFlow 1.3.27 / sequence 1228 — source-freeze closure

> **SUPERSEDED BEFORE BUILD:** This initial freeze boundary was first
> superseded by the Python 3.13 patch-compatibility bridge and was later
> superseded again after the final pre-release integrity/performance closure.
> Current source authority is documented in
> `CLIENTFLOW_1.3.27_1228_POST_MAINTENANCE_FINAL_SOURCE_REFREEZE_CLOSURE.md`.

## Scope

This source-freeze change stages the current canonical codebase as ClientFlow
1.3.27 / sequence 1228 so the canonical runtime-input transport and release
build workflows can operate on a source identity exactly one sequence ahead of
the currently promoted runtime catalog.

No runtime selector is promoted by this change.

## Frozen candidate identity

- `client/VERSION = 1.3.27`;
- `release_sequence = 1228`;
- candidate release id: `clientflow-1.3.27-seq-1228`;
- minimum Ubuntu LTS: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`.

## Catalog boundary

The runtime catalog remains unchanged on:

- catalog sequence `1227`;
- latest/default version `1.3.26`;
- selected release `clientflow-1.3.26-seq-1227`.

Regression contracts require source sequence 1228 to lead catalog sequence 1227
by exactly one until the 1228 candidate has crossed the required release gates.

## Source-freeze decision

**PASS for source freeze**, subject to canonical GitHub CI after merge.

The immediate next gate is deterministic runtime-input transport for sequence
1228 using the exact green `main` source SHA produced by this source-freeze
merge.
