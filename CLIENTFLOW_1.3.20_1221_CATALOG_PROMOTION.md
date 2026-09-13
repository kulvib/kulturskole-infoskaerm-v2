# ClientFlow 1.3.20 / sequence 1221 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.20-seq-1221`
- source commit: `7391dcfee0b77eddd46f7b8a986ae442b64d3fcc`
- approved bundle SHA-256: `64df5b844b6dc3ffa1579f6477142a99e80b747d66825900b957c4af8ee01941`
- approved bundle size: `223098880`
- candidate SHA-256: `cc5fa23b5ba7bc003cd816dc63ccc0b1054d438a177c9200c73dc5f99c63401a`
- installer SHA-256: `a9cd3b14a876301235d2be89e298415076510ec206d1cb6b251b96e7e4ab81c0`
- approval reference: `clientflow-1.3.20-seq-1221/operator-approval-2026-09-13`

## Completed gates before promotion

1. Exact-source canonical push CI passed.
2. Runtime-input transport was verified against the repo-pinned platform lock.
3. Two independent release-build runners produced byte-identical candidates.
4. The Ubuntu 26.04 executable candidate gate passed.
5. The exact reproducible candidate was manually approved with the immutable
   approval reference above.
6. The approved bundle was transported through a GitHub prerelease explicitly
   marked transport-only.
7. The exact approved bytes were published to
   `/var/data/clientflow-release-artifacts/store/clientflow-1.3.20-seq-1221.tar`.
8. The stored file was independently re-read and matched both approved size and
   SHA-256 exactly.

## Catalog policy after promotion

- `catalog_sequence = 1221`
- `latest_stable = 1.3.20`
- `default_install_version = 1.3.20`
- the single selectable release is `clientflow-1.3.20-seq-1221`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the
  canonical safe in-place update baseline enforced by backend policy.

The catalog deliberately does not duplicate bundle hashes, approval references
or source commit as selector metadata. Those values remain authoritative in the
immutable published artifact inspected by the backend artifact layer.

## Next gate

After full GitHub CI and deployment of this promotion, perform a canonical clean
Ubuntu 26.04 fresh-install verification of 1.3.20/1221 with no diagnostic bypass.
Physical GUI pixel-parity against the deployed legacy 1.1.19 contract remains a
separate acceptance point.
