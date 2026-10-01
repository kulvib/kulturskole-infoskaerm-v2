# ClientFlow 1.3.28 / sequence 1229 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.28-seq-1229`
- source commit: `fdd230ab9939791491213794dafa57b9223fc7c8`
- exact-source CI: `#1174` / run `36832356569` / success
- runtime-input transport tag: `runtime-inputs-1229-fdd230ab9939791491213794dafa57b9223fc7c8-transport`
- runtime-input transport workflow: `#12` / run `36890463537` / success
- runtime-input transport SHA-256: `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- release build: `#33` / run `36891233613` / success
- candidate SHA-256: `2491130d1c6411a0b98bf35d0d4bcafb1a55451db7caee823903e6e8a4dfb10c`
- payload SHA-256: `2a62d0319cd344c2eacfe65003fe8a7abf690d74e96612ff2c1028d3e8109ca1`
- installer SHA-256: `c316086d036704a1acc259f50de4f71d0cad83888057d88e73484ffb25d3fce4`
- approval: `#16` / run `36892482248` / success
- approval reference: `clientflow-1.3.28-seq-1229/fdd230ab9939791491213794dafa57b9223fc7c8/manual-approval`
- approved bundle SHA-256: `d48703fc4917b8a18c32f787899169d8098436d616c3afb636b1968ea85fdc01`
- approved bundle size: `224153600`
- approved transport tag: `clientflow-1.3.28-1229-approved-transport`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.28-seq-1229.tar`

Sequence `1228` is intentionally absent from selector authority. The immutable
1.3.27/1228 bundle was security-rejected before catalog promotion due
CVE-2026-101918 and remains historical evidence only.

## Completed gates before promotion

1. Exact source commit `fdd230ab9939791491213794dafa57b9223fc7c8` passed canonical CI #1174 / run `36832356569`.
2. Runtime-input transport #12 / run `36890463537` published deterministic source-SHA-qualified sequence-1229 platform inputs at the SHA-256 above.
3. Canonical release-build #33 / run `36891233613` produced two byte-identical independent candidates.
4. The Ubuntu 26.04 executable-candidate gate passed.
5. Approval #16 / run `36892482248` explicitly approved the exact reproducible candidate with the immutable approval reference above.
6. The approved bundle was transported through GitHub prerelease `clientflow-1.3.28-1229-approved-transport`, explicitly marked transport-only.
7. The GitHub asset re-read at exactly `224153600` bytes and SHA-256 `d48703fc4917b8a18c32f787899169d8098436d616c3afb636b1968ea85fdc01`.
8. The exact approved bytes were published by `scripts/publish_clientflow_release.py` into the canonical Render immutable artifact-store path above.
9. The stored file was independently re-read at exactly `224153600` bytes and matched the approved SHA-256 exactly.
10. Runtime catalog selection remained 1.3.26/1227 throughout build, approval, transport, publication and independent re-read.
11. Immutable 1.3.27/1228 remained security-rejected throughout and was never added to the selectable catalog.

## Catalog policy after promotion

- `catalog_sequence = 1229`
- `latest_stable = 1.3.28`
- `default_install_version = 1.3.28`
- the single selectable release is `clientflow-1.3.28-seq-1229`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the canonical safe in-place update baseline enforced by backend policy
- embedded runtime Python remains `3.13.14`; this release is the security-fixed compatibility bridge before any later Python 3.13.15 runtime upgrade
- embedded PyJWT is patched to `2.15.1`
- rollback remains disabled and the controlled reboot remains required
- retention remains one installable release in catalog metadata
- sequence 1228 remains permanently non-selectable

The catalog deliberately does not duplicate bundle hashes, approval references,
candidate hashes or source commit as selector fields. Those values remain
authoritative in the immutable published artifact and this promotion record.

## Scope boundary

This promotion changes runtime selection only. It does not modify ClientFlow
runtime implementation, source/build identity, release-build bytes, installer
bytes, approved bundle bytes, approval metadata or the immutable artifact store.

## Next gate

After full GitHub CI, merge and backend deployment of this promotion, verify that
the running backend reports 1.3.28/1229 as the only stable/default fresh-install
selection while the immutable store still re-reads the exact approved 1229
SHA-256. Then physically verify the promoted 1.3.26 -> 1.3.28 compatibility-bridge
in-place update on Ubuntu Desktop 26.04 before staging any release that advances
the embedded runtime to Python 3.13.15. Regenerate and verify the canonical
ClientFlow preparation USB from promoted main and repeat clean Ubuntu Desktop
26.04 fresh-install acceptance from phase 0.
