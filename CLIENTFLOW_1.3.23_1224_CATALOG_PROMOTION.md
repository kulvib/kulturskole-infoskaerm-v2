# ClientFlow 1.3.23 / sequence 1224 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.23-seq-1224`
- source commit: `98380ac6254f9bbd214223c3f6a1703d3a13c732`
- canonical push CI: `#762` / run `35450877273` / success
- runtime-input transport: `runtime-inputs-1224-transport`
- runtime-input transport SHA-256: `233e2e36323bcb7c15bf3d44eeb03c46a00edf84746a50598cde18d565976619`
- release build run: `35451916491`
- candidate SHA-256: `2d3a6f28856920295fe3e6129cb8edd667bb13f18796dbbdba2ce1c581576cc1`
- payload SHA-256: `8f0b5a9a533ba5c271d5e4d8b48b26f3df9ad5ccf9e6563cd56f94f4677d70ef`
- installer SHA-256: `ef8c2da74631225cf8c3bc6aaecd1b680060798fbfcaf154ff1aa61fcf3ed045`
- approval run: `35452848379`
- approval reference: `clientflow-1.3.23-seq-1224/manual-approval/candidate-2d3a6f28856920295fe3e6129cb8edd667bb13f18796dbbdba2ce1c581576cc1`
- approved bundle SHA-256: `32241e0e2db55d2345a3144e6c11bb9c80aaf99c07ec061ba1358a8b8bb4b53c`
- approved bundle size: `223119360`
- approved transport tag: `clientflow-1.3.23-1224-approved-transport`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.23-seq-1224.tar`

## Completed gates before promotion

1. The exact re-frozen source commit passed canonical push CI.
2. The sequence-1224 runtime-input transport was published as transport-only and
   independently bound to the current repo platform lock.
3. Canonical release-build run `35451916491` produced two byte-identical
   independent 1.3.23/1224 candidates.
4. The Ubuntu 26.04 executable-candidate gate passed.
5. The exact reproducible candidate was manually approved by approval run
   `35452848379` with the immutable approval reference above.
6. The approved bundle was transported through GitHub prerelease
   `clientflow-1.3.23-1224-approved-transport`, explicitly marked transport-only.
7. The transport asset re-read at exactly `223119360` bytes and SHA-256
   `32241e0e2db55d2345a3144e6c11bb9c80aaf99c07ec061ba1358a8b8bb4b53c`.
8. The exact approved bytes were published into the canonical Render immutable
   artifact store path above using `scripts/publish_clientflow_release.py`.
9. The stored file was independently re-read and matched the approved size and
   SHA-256 exactly.
10. The stored manifest proved `deployable: true`, release id/version/sequence,
    source commit, approval reference and embedded installer SHA-256.
11. The runtime catalog remained 1.3.22/1223 throughout approval, transport,
    publication and independent store verification.

## Catalog policy after promotion

- `catalog_sequence = 1224`
- `latest_stable = 1.3.23`
- `default_install_version = 1.3.23`
- the single selectable release is `clientflow-1.3.23-seq-1224`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the
  canonical safe in-place update baseline enforced by backend policy
- rollback remains disabled and the controlled reboot remains required
- retention remains one installable release in catalog metadata

The catalog deliberately does not duplicate bundle hashes, approval references,
candidate hashes or source commit as selector fields. Those values remain
authoritative in the immutable published artifact and this promotion record.

## Included release closures

The promoted release contains the completed two-phase factory/customer install
lifecycle, including office-side account provisioning/network scrub, the no-sudo
customer `02 Aktiver ClientFlow` handoff, exact-release fresh-install authority,
resumable ambiguous claims, pending-manual-activation GUI and automatic first
activation after backend approval.

It also contains the merged database/request efficiency work, request
observability, shared live-state polling consolidation, direct browser-to-backend
API transport and auth-route churn closure. Production acceptance measured the
direct transport at 125.4 ms median for `/clients/` versus 840.9 ms through the
former Render rewrite and 119 ms for `/chrome-status` versus 427.6 ms.

## Scope boundary

This promotion changes runtime selection only. It does not modify Livestream,
Terminal, Remote Desktop, ClientFlow runtime implementation, release build bytes,
installer bytes, approved bundle bytes or the immutable artifact store.

## Next gate

After full GitHub CI, merge and deployment of this promotion, verify that the
running backend reports 1.3.23/1224 as the only selectable stable/fresh-install
release while the immutable store still re-reads the exact approved bundle SHA.
Then regenerate and verify the canonical ClientFlow preparation USB from promoted
main and restart the clean Ubuntu Desktop 26.04 physical fresh-install acceptance
from phase 0: `01 Klient klargøring` -> reboot -> `02 Aktiver ClientFlow` ->
pending GUI -> backend approval -> automatic canonical activation -> healthy
active runtime.
