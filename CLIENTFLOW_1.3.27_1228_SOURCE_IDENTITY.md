# ClientFlow 1.3.27 / sequence 1228 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the
canonical 1.3.26 / 1227 release was approved, published, promoted and retained
as the sole runtime selector authority.

Canonical authority before this identity transition:

- source/build identity: `1.3.26 / 1227`;
- runtime catalog: `clientflow-1.3.26-seq-1227`;
- catalog sequence: `1227`;
- minimum Ubuntu LTS: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`.

The exact Git commit SHA is not embedded in the uploaded archive. The
40-character source-freeze SHA must be taken from GitHub after this change is
merged to `main` and canonical CI is green.

Staged source/build identity after this change:

- version: `1.3.27`;
- release sequence: `1228`;
- candidate release id: `clientflow-1.3.27-seq-1228`.

This document is source/build identity only. It is not approval, publication or
catalog-promotion authority.

## Release-gate separation

The runtime catalog deliberately remains on the last approved, published and
promoted selector authority:

- `catalog_sequence = 1227`;
- `latest_stable = 1.3.26`;
- `default_install_version = 1.3.26`;
- selected release = `clientflow-1.3.26-seq-1227`.

The source/build identity therefore leads the catalog by exactly one sequence,
which is the invariant required by `.github/workflows/runtime-input-transport.yml`.
The catalog must not select 1.3.27/1228 until the exact candidate has passed the
canonical release gates and the approved bytes have been immutably published
and independently re-read.

## Next gates

After merge and green canonical CI:

1. record the exact resulting 40-character `main` SHA;
2. run runtime-input transport for sequence 1228 from that exact SHA;
3. record the emitted runtime-input URL and SHA-256;
4. run the canonical reproducible release build for that same SHA and transport;
5. continue through candidate acceptance, manual approval, immutable publication,
   catalog promotion, canonical USB and physical clean-client acceptance.
