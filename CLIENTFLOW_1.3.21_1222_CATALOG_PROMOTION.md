# ClientFlow 1.3.21 / sequence 1222 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.21-seq-1222`
- source commit: `6c0319c931859cca9c64a6e31606ad729c92fac7`
- approved bundle SHA-256: `583d8b1742a456a047ad64bbbc67aa65732483321bad3ae31e1a7569ab8a2909`
- approved bundle size: `223098880`
- candidate SHA-256: `30199b8691428765c7c943acc7af0cc12aaae1f38969806a4c197ef981535099`
- installer SHA-256: `f6af58a5735acc8e95df3dd655b9de4c62fadf95f51606c3ea45235ba276c4dc`
- approval reference: `clientflow-1.3.21-seq-1222-manual-approval-30199b8691428765`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.21-seq-1222.tar`

## Completed gates before promotion

1. Exact source-freeze canonical push CI passed for
   `6c0319c931859cca9c64a6e31606ad729c92fac7`.
2. Runtime-input transport was verified against the repo-pinned platform lock.
3. Two independent release-build runners produced byte-identical candidates.
4. The Ubuntu 26.04 executable-candidate gate passed.
5. The exact reproducible candidate was manually approved with the immutable
   approval reference above.
6. The approved bundle was transported through a GitHub prerelease explicitly
   marked transport-only.
7. The exact approved bytes were published to the canonical Render immutable
   artifact store path above.
8. The stored file was independently re-read and matched approved size and
   SHA-256 exactly.
9. The re-read manifest proved `deployable: true`, source commit, candidate
   SHA-256, approval reference and embedded installer SHA-256.
10. The runtime catalog was still `1.3.20/1221` throughout publication and
    independent re-read.

## Catalog policy after promotion

- `catalog_sequence = 1222`
- `latest_stable = 1.3.21`
- `default_install_version = 1.3.21`
- the single selectable release is `clientflow-1.3.21-seq-1222`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the
  canonical safe in-place update baseline enforced by backend policy
- rollback remains disabled and the controlled reboot remains required

The catalog deliberately does not duplicate bundle hashes, approval references,
candidate hashes or source commit as selector metadata. Those values remain
authoritative in the immutable published artifact and this promotion record.

## Scope boundary

This promotion changes runtime selection only. It does not modify Livestream,
Terminal, Remote Desktop, ClientFlow runtime implementation, release build bytes,
installer bytes or the immutable artifact store.

## Next gate

After full GitHub CI, merge and deployment of this promotion, verify that the
running backend reports `1.3.21/1222` as the only selectable stable/fresh-install
release while the immutable store still re-reads the exact approved bundle SHA.
Then perform a genuinely clean Ubuntu 26.04 physical fresh-install verification
of 1.3.21/1222 with no diagnostic bypass, followed by final GUI/process parity
acceptance against deployed legacy 1.1.19.
