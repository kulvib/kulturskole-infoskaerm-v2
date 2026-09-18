# ClientFlow 1.3.22 / sequence 1223 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.22-seq-1223`
- source commit: `957f5d7ab7a3c7fc835565c041533df30834dd78`
- approved bundle SHA-256: `ca8e3b0713ae3af8fec018083235409d662aac70e71eb5062cbbe60bc4aaa6d4`
- approved bundle size: `223098880`
- candidate SHA-256: `bd9613043d5e770c8b18c53d7550fa577d351dbb5fb47ea50bf7850350c06261`
- installer SHA-256: `5e9cf308dd54f79eeb2c1feec4c37935f1b8f4d8f8ee0d74ea7af16905c732e4`
- payload SHA-256: `b71b054d5a8d4b1a13f7cd41c6291288589a75653579e07687331e352f22d09f`
- approval reference: `clientflow-1.3.22-seq-1223-manual-approval-bd9613043d5e770c`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.22-seq-1223.tar`

## Completed gates before promotion

1. Exact source-freeze canonical push CI #709 / run `35340069332` passed for
   `957f5d7ab7a3c7fc835565c041533df30834dd78`.
2. The unchanged repo-pinned runtime platform inputs were transported through
   the existing transport-only artifact and reverified against the platform lock.
3. Canonical release-build run `35340730441` produced two byte-identical
   independent 1.3.22/1223 candidates.
4. The Ubuntu 26.04 executable-candidate gate passed.
5. The exact reproducible candidate was manually approved by approval run
   `35341401418` with the immutable approval reference above.
6. The approved bundle was transported through GitHub prerelease
   `clientflow-1.3.22-1223-approved-transport`, explicitly marked transport-only.
7. The exact approved bytes were published to the canonical Render immutable
   artifact store path above.
8. The stored file was independently re-read and matched approved size and
   SHA-256 exactly.
9. The re-read manifest proved `deployable: true`, source commit, candidate
   SHA-256, approval reference and embedded installer SHA-256.
10. The runtime catalog remained `1.3.21/1222` throughout publication and the
    post-publication authority gate.
11. Before publication, unused immutable bundles 1.3.18/1219, 1.3.19/1220 and
    1.3.20/1221 were removed only after proving there were no active unexpired
    enrollment bindings or non-terminal deployments referencing them. The then
    active 1.3.21/1222 bundle was preserved exactly.

## Catalog policy after promotion

- `catalog_sequence = 1223`
- `latest_stable = 1.3.22`
- `default_install_version = 1.3.22`
- the single selectable release is `clientflow-1.3.22-seq-1223`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the
  canonical safe in-place update baseline enforced by backend policy
- rollback remains disabled and the controlled reboot remains required
- retention remains one installable release in catalog metadata

The catalog deliberately does not duplicate bundle hashes, approval references,
candidate hashes or source commit as selector fields. Those values remain
authoritative in the immutable published artifact and this promotion record.

## Scope boundary

This promotion changes runtime selection only. It does not modify Livestream,
Terminal, Remote Desktop, ClientFlow runtime implementation, release build bytes,
installer bytes, approved bundle bytes or the immutable artifact store.

## Next gate

After full GitHub CI, merge and deployment of this promotion, verify that the
running backend reports `1.3.22/1223` as the only selectable stable/fresh-install
release while the immutable store still re-reads the exact approved bundle SHA.
Then build and verify a genuinely canonical USB from the promoted main and restart
the clean Ubuntu Desktop 26.04 physical fresh-install verification from the
beginning, specifically re-proving the desktop launcher execution closure and
PlanIQ Display icon branding without diagnostic bypasses.
