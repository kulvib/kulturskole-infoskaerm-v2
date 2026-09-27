# ClientFlow 1.3.26 / sequence 1227 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.26-seq-1227`
- source commit: `dcd462b5dcbef15b6c0c645158130c0baf8296e6`
- exact-source CI: `#998` / run `36313640352` / success
- runtime-input transport: `runtime-inputs-1227-transport`
- runtime-input transport workflow: `#6` / run `36308867283` / success
- runtime-input transport SHA-256: `233e2e36323bcb7c15bf3d44eeb03c46a00edf84746a50598cde18d565976619`
- release build: `#29` / run `36309087012` / success
- candidate SHA-256: `86ba0079e0c7f6f946eda290ad2e570cc479d13db87aca3480bfd53687c4d231`
- payload SHA-256: `cfdc39983d99e20ba98075fddf7c6b7634820448567425d8efad5512c008b855`
- installer SHA-256: `980e5848d7fe1003a5f3fd92465a0c043f1ccbe53d2e42b896cece1195881412`
- approval: `#13` / run `36312940147` / success
- approval reference: `clientflow-1.3.26-seq-1227/manual-approval/candidate-86ba0079e0c7f6f946eda290ad2e570cc479d13db87aca3480bfd53687c4d231`
- approved bundle SHA-256: `9d96d8f19eaae468dd8902d71cffba3ae26f468353f095bf920c5ad937d16a3d`
- approved bundle size: `223139840`
- approved transport tag: `clientflow-1.3.26-1227-approved-transport`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.26-seq-1227.tar`

## Completed gates before promotion

1. Exact source commit `dcd462b5dcbef15b6c0c645158130c0baf8296e6` passed exact-source CI #998 / run `36313640352`.
2. Runtime-input transport #6 / run `36308867283` published deterministic sequence-1227 platform inputs at the repo-locked SHA-256 above.
3. Canonical release-build #29 / run `36309087012` produced two byte-identical independent candidates.
4. The Ubuntu 26.04 executable-candidate gate passed.
5. Approval #13 / run `36312940147` explicitly approved the exact reproducible candidate with the immutable approval reference above.
6. The approved bundle was transported through GitHub prerelease `clientflow-1.3.26-1227-approved-transport`, explicitly marked transport-only.
7. The GitHub asset re-read at exactly `223139840` bytes and SHA-256 `9d96d8f19eaae468dd8902d71cffba3ae26f468353f095bf920c5ad937d16a3d`.
8. The exact approved bytes were published by `scripts/publish_clientflow_release.py` into the canonical Render immutable artifact-store path above.
9. The stored file was independently re-read as a regular 223139840-byte file and matched the approved SHA-256 exactly.
10. The running Render checkout was independently verified clean at exact source commit, version 1.3.26 / sequence 1227, and its canonical SHA256SUMS gate passed.
11. Runtime catalog selection remained 1.3.25/1226 throughout build, approval, transport, publication and independent re-read.

## Catalog policy after promotion

- `catalog_sequence = 1227`
- `latest_stable = 1.3.26`
- `default_install_version = 1.3.26`
- the single selectable release is `clientflow-1.3.26-seq-1227`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the canonical safe in-place update baseline enforced by backend policy
- rollback remains disabled and the controlled reboot remains required
- retention remains one installable release in catalog metadata

The catalog deliberately does not duplicate bundle hashes, approval references,
candidate hashes or source commit as selector fields. Those values remain
authoritative in the immutable published artifact and this promotion record.

## Included 1227 closures

The promoted release includes the completed post-1226 closure:

- factory post-reboot readiness proof before backend approval;
- Terminal admin Enter/support-command UX closure without weakening authority;
- Remote Desktop kiosk-home file parity rooted at `/home/clientflow-kiosk`;
- local GUI legacy status/layout parity without exposing administrator access;
- domain-scoped Control Room configuration actions;
- lockdown observed-state enforcement/drift detection;
- permanent kiosk notification-banner suppression and command-line baseline;
- conservative non-removing Ubuntu-update package-health gate;
- repository/database-performance audit closure with no speculative optimization.

Livestream, product Terminal and Remote Desktop capability semantics remain frozen
except for the explicitly completed parity/UX scopes above.

## Scope boundary

This promotion changes runtime selection only. It does not modify ClientFlow
runtime implementation, source/build identity, release-build bytes, installer
bytes, approved bundle bytes, approval metadata or the immutable artifact store.

## Next gate

After full GitHub CI, merge and backend deployment of this promotion, verify that
the running backend reports 1.3.26/1227 as the only stable/default fresh-install
selection while the immutable store still re-reads the exact approved 1227
SHA-256. Then regenerate and verify the canonical ClientFlow preparation USB from
promoted main and restart clean Ubuntu Desktop 26.04 physical fresh-install
acceptance from phase 0: `01 Klient klargøring` -> reboot -> `02 Aktiver ClientFlow`
-> pending GUI -> backend approval -> automatic canonical activation -> healthy
active runtime.
