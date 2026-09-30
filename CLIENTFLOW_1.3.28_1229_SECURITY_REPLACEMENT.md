# ClientFlow 1.3.28 / sequence 1229 — security replacement for rejected 1.3.27 / 1228

Date: 2026-09-30

## Status

**SECURITY REPLACEMENT STAGED. 1.3.27 / 1228 must not be catalog-promoted.**

The already built, manually approved and immutably published
`clientflow-1.3.27-seq-1228` bundle contains PyJWT `2.13.0` in its embedded
ClientFlow runtime. CVE-2026-101918 / GHSA-42vr-xj54-vc7v affects PyJWT
versions before `2.15.0`, including the `verify_signature=False` decoding path
used by ClientFlow runtime token inspection. The backend source at the same
boundary used PyJWT `2.14.0` and is affected as well.

Because the 1228 bundle has crossed the immutable publication boundary, its
release identity and bytes are retained as historical evidence and are never
overwritten or reused. The runtime catalog remains on the last promoted safe
selector authority, `1.3.26 / 1227`.

## Replacement identity

The next candidate identity is therefore:

- version: `1.3.28`;
- release sequence: `1229`;
- candidate release id: `clientflow-1.3.28-seq-1229`;
- catalog sequence remains: `1227`;
- catalog latest/default remains: `1.3.26`;
- embedded runtime Python remains: `3.13.14`.

The two-sequence source/catalog gap is intentional and exact: sequence 1228 is
consumed by the rejected immutable bundle. It does not authorize selecting or
installing 1228.

## Security remediation

Both active dependency authorities are raised to PyJWT `2.15.1`:

- backend/CI direct dependency and hash locks;
- ClientFlow embedded runtime dependency, runtime-input lock and release-build
  wheel contracts.

PyJWT `2.15.1` is above the advisory-fixed floor (`2.15.0`) and remains
compatible with Python `3.13.14`. The embedded Python version itself is not
advanced: 1.3.28/1229 remains the compatibility bridge consumable by the
currently promoted 1.3.26/1227 updater.

The runtime-input transport supports replacing the exact stale PyJWT wheel from
the previously verified 1228 transport with the exact current locked 2.15.1
wheel. The replacement wheel is downloaded only over HTTPS and is accepted
only if its size and SHA-256 match `client/release/runtime-platform-inputs.lock.json`.
All reused bytes remain independently reverified against the same lock, and the
final transport is still built twice and required to be byte-identical.

## Release authority

This source change invalidates the 1228 candidate/approval chain for promotion.
The existing 1228 approval and immutable artifact remain historical evidence
only. 1.3.28/1229 must complete a new exact-source chain:

1. merge this security replacement and require green canonical CI;
2. freeze the exact resulting `main` SHA;
3. build a new source-SHA-qualified runtime-input transport for sequence 1229;
4. run the canonical reproducible release build;
5. require Ubuntu 26.04 executable-candidate verification and byte-identical
   independent builds;
6. manually approve that exact candidate;
7. publish its approved bytes immutably under the 1229 identity;
8. only then promote the catalog directly from 1.3.26/1227 to 1.3.28/1229;
9. physically verify the promoted update path before any later runtime-Python
   upgrade to 3.13.15.
