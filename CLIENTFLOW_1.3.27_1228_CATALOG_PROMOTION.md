# ClientFlow 1.3.27 / sequence 1228 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.27-seq-1228`
- source commit: `8525ecf5491a1dfb16cc6880302020e83dac74f5`
- exact-source CI: `#1163` / run `36736291011` / success
- runtime-input transport: `runtime-inputs-1228-8525ecf5491a1dfb16cc6880302020e83dac74f5-transport`
- runtime-input transport workflow: `#11` / run `36745977741` / success
- runtime-input transport SHA-256: `233e2e36323bcb7c15bf3d44eeb03c46a00edf84746a50598cde18d565976619`
- runtime-input transport size: `222248960`
- release build: `#32` / run `36746566035` / success
- candidate SHA-256: `0ccc84f3d615f574587a5dfaf754cd62174815b6b2baece859f3e7f9ab9617e5`
- payload SHA-256: `732fcd92529f4da4ab1630993849bc964d85ba5d551f950e32cc3736f84cd0f6`
- installer SHA-256: `00c4c30e32c8331f4498b3e8ea4acc901c9f7c1aa284ffdae681a077f74a6d16`
- approval: `#15` / run `36749143723` / attempt 2 / success
- approval reference: `clientflow-1.3.27-seq-1228/manual-approval/candidate-0ccc84f3d615f574587a5dfaf754cd62174815b6b2baece859f3e7f9ab9617e5`
- approved bundle SHA-256: `4ef9c294454f1234a55e6e0257a81a060ee8ab99a3aa0f33de1ba55d99108601`
- approved bundle size: `224153600`
- approved transport tag: `clientflow-1.3.27-1228-approved-transport`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.27-seq-1228.tar`
- embedded runtime Python: `3.13.14`

## Completed gates before promotion

1. Exact source commit `8525ecf5491a1dfb16cc6880302020e83dac74f5` passed canonical CI #1163 / run `36736291011`.
2. Source-SHA-qualified runtime-input transport #11 / run `36745977741` published the exact sequence-1228 Python 3.13.14 platform inputs at the repo-locked SHA-256 above.
3. Canonical release-build #32 / run `36746566035` produced two byte-identical independent candidates and passed the Ubuntu 26.04 executable-candidate gate.
4. Approval #15 / run `36749143723`, attempt 2, explicitly approved the exact reproducible candidate with the immutable approval reference above.
5. The approved bundle was transported through GitHub prerelease `clientflow-1.3.27-1228-approved-transport`, explicitly marked transport-only.
6. The GitHub asset re-read at exactly `224153600` bytes and SHA-256 `4ef9c294454f1234a55e6e0257a81a060ee8ab99a3aa0f33de1ba55d99108601`.
7. The exact approved bytes were published by `scripts/publish_clientflow_release.py` into the canonical Render immutable artifact-store path above.
8. The stored file was independently re-read and matched the approved SHA-256 exactly.
9. Runtime catalog selection remained 1.3.26/1227 throughout build, approval, transport, publication and independent re-read.

## Catalog policy after promotion

- `catalog_sequence = 1228`
- `latest_stable = 1.3.27`
- `default_install_version = 1.3.27`
- the single selectable release is `clientflow-1.3.27-seq-1228`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the canonical safe in-place update baseline enforced by backend policy
- rollback remains disabled and the controlled reboot remains required
- retention remains one installable release in catalog metadata
- embedded runtime Python remains `3.13.14` for the promoted 1.3.26 -> 1.3.27 compatibility bridge

The catalog deliberately does not duplicate bundle hashes, approval references,
candidate hashes or source commit as selector fields. Those values remain
authoritative in the immutable published artifact and this promotion record.

## Included 1228 closures

The promoted release includes the completed pre-release maintenance wave,
including backend/frontend toolchain maintenance, dependency/security updates,
database-cost and Livestream query-frequency reductions, repository hygiene and
CI critical-path optimization. The ClientFlow embedded runtime remains on Python
3.13.14 for this bridge release; the separately proven Python 3.13.15 runtime
candidate remains authority only for a later post-1228 release.

Existing activation, security, fresh-install, Terminal, Remote Desktop,
Livestream and Display authority boundaries remain unchanged except for the
explicitly completed and already frozen 1.3.27/1228 scopes.

## Scope boundary

This promotion changes runtime selection only. It does not modify ClientFlow
runtime implementation, source/build identity, release-build bytes, installer
bytes, approved bundle bytes, approval metadata or the immutable artifact store.

## Next gate

After full GitHub CI, merge and backend deployment of this promotion, verify that
the running backend reports 1.3.27/1228 as the only stable/default fresh-install
selection while the immutable store still re-reads the exact approved 1228
SHA-256. Then regenerate and verify the canonical ClientFlow preparation USB,
restart clean Ubuntu Desktop 26.04 physical fresh-install acceptance from phase
0, and verify the promoted 1.3.26 -> 1.3.27 in-place bridge update path before
staging any later embedded-runtime Python upgrade.
