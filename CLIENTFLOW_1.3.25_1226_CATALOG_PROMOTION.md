# ClientFlow 1.3.25 / sequence 1226 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.25-seq-1226`
- source commit: `dd023dda80bac080f6ec5ba87e0d2ce8eb76dbe6`
- canonical push CI: `#888` / run `35770069127` / success
- runtime-input transport: `runtime-inputs-1226-transport`
- runtime-input transport workflow: `#5` / run `35830226298` / success
- runtime-input transport SHA-256: `233e2e36323bcb7c15bf3d44eeb03c46a00edf84746a50598cde18d565976619`
- release build: `#28` / run `35831098680` / success
- candidate SHA-256: `e3fa9b8642d3ae74e62ab1f39735e66fabbd3ec301575dd91af23a92d1bb8c89`
- payload SHA-256: `dfc57bafac6699a959023f1691f78c1d8ab1ace2ac24354d181390c8304c9101`
- installer SHA-256: `99a3aa82b5f593da1086d5a0b14451ba770a70b3baabf3bf9926e230fabc0582`
- approval: `#12` / run `35833279042` / success
- approval reference: `clientflow-1.3.25-seq-1226/manual-approval/candidate-e3fa9b8642d3ae74e62ab1f39735e66fabbd3ec301575dd91af23a92d1bb8c89`
- approved bundle SHA-256: `03bd9ea2364f1b20916a5fe314cecf5e9d9c4c8b79e94048ca5fe5c5bd5d6992`
- approved bundle size: `223119360`
- approved transport tag: `clientflow-1.3.25-1226-approved-transport`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.25-seq-1226.tar`

## Completed gates before promotion

1. Exact source commit `dd023dda80bac080f6ec5ba87e0d2ce8eb76dbe6` passed canonical main push CI #888 / run `35770069127`.
2. Runtime-input transport #5 / run `35830226298` published deterministic sequence-1226 platform inputs at the repo-locked SHA-256 above.
3. Canonical release-build #28 / run `35831098680` produced two byte-identical independent candidates.
4. The Ubuntu 26.04 executable-candidate gate passed.
5. Approval #12 / run `35833279042` explicitly approved the exact reproducible candidate with the immutable approval reference above.
6. The approved bundle was transported through GitHub prerelease `clientflow-1.3.25-1226-approved-transport`, explicitly marked transport-only.
7. The GitHub asset re-read at exactly `223119360` bytes and SHA-256 `03bd9ea2364f1b20916a5fe314cecf5e9d9c4c8b79e94048ca5fe5c5bd5d6992`.
8. The exact approved bytes were published by `scripts/publish_clientflow_release.py` into the canonical Render immutable artifact-store path above.
9. The stored file was independently re-read as a regular 223119360-byte file and matched the approved SHA-256 exactly.
10. The stored file was byte-compared with the verified GitHub transport and the stored manifest proved `deployable: true`, exact release id/version/sequence, source commit and approval reference.
11. Runtime catalog selection remained 1.3.24/1225 throughout build, approval, transport, artifact-store cleanup, publication and independent re-read.

## Artifact-store capacity cleanup before publication

The 1 GiB Render persistent disk could not hold a fifth ~223 MB release. Before
publishing 1226, the store was checked fail-closed against production database
authority. There were zero active/unconsumed CF codes and zero incomplete
deployments bound to 1222-1224. Their exact approved bundles were independently
verified by size/SHA-256 and remain available as GitHub approved-transport assets.
Only those three non-selected historical store copies were removed. The selected
1.3.24/1225 bundle was preserved byte-identically. After cleanup, 1226 publication
succeeded and the Render store contained only 1225 and 1226.

This storage cleanup does not change catalog selection, release bytes, approval
authority or rollback policy. Historical GitHub transport assets remain recovery
and provenance copies; they are not runtime catalog authority.

## Catalog policy after promotion

- `catalog_sequence = 1226`
- `latest_stable = 1.3.25`
- `default_install_version = 1.3.25`
- the single selectable release is `clientflow-1.3.25-seq-1226`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the canonical safe in-place update baseline enforced by backend policy
- rollback remains disabled and the controlled reboot remains required
- retention remains one installable release in catalog metadata

The catalog deliberately does not duplicate bundle hashes, approval references,
candidate hashes or source commit as selector fields. Those values remain
authoritative in the immutable published artifact and this promotion record.

## Included 1226 closures

The promoted release includes the completed pre-1226 closure:

- exact/local GUI parity against the pinned legacy 1.1.19 operator layout without exposing administrator access;
- hot-path ClientFlow agent DB/request reductions and calendar/organization batching;
- Control Room adaptive polling/narrow payload and Client Details hot-state deduplication;
- Display/System heartbeat+claim and update-plane idle request consolidation;
- calendar conditional delivery with durable 56A revision metadata and unchanged 15-second propagation cadence;
- terminal-dialog UX simplification while preserving all security checks and engineering CLI JSON;
- removal of five proven-unused source/runtime/template artifacts before the final source SHA;
- production Neon read-only pre-freeze audit with no release-blocking database finding.

Livestream, product Terminal and Remote Desktop implementation semantics remain
frozen in this release.

## Scope boundary

This promotion changes runtime selection only. It does not modify ClientFlow
runtime implementation, source/build identity, release-build bytes, installer
bytes, approved bundle bytes, approval metadata or the immutable artifact store.

## Next gate

After full GitHub CI, merge and backend deployment of this promotion, verify that
the running backend reports 1.3.25/1226 as the only stable/default fresh-install
selection while the immutable store still re-reads the exact approved 1226
SHA-256. Then regenerate and verify the canonical ClientFlow preparation USB from
promoted main and start clean Ubuntu Desktop 26.04 physical fresh-install
acceptance from phase 0: `01 Klient klargøring` -> reboot -> `02 Aktiver ClientFlow`
-> pending GUI -> backend approval -> automatic canonical activation -> healthy
active runtime.
