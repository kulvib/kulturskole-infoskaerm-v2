# ClientFlow 1.3.31 / sequence 1232 — fresh-install-only catalog promotion

## Purpose

This change promotes the already approved, transported and immutably published
ClientFlow 1.3.31/1232 bytes as the canonical **fresh-install** target. It does
not claim or authorize in-place update compatibility.

The promotion follows the corrected release order for the normal USB/operator
path: reproducible candidate -> exact-byte approval -> immutable publication ->
catalog promotion/redeploy -> physical fresh-install acceptance. Approval and
publication are release-mechanics gates; they do not claim that physical
acceptance has passed.

## Immutable authority chain

- release id: `clientflow-1.3.31-seq-1232`
- source commit: `aa9a57caa7a08fed17baaa0395a6638173f0e265`
- exact-source canonical CI: green before runtime-input transport dispatch
- runtime-input transport: `#16` / success
- runtime-input transport tag: `runtime-inputs-1232-aa9a57caa7a08fed17baaa0395a6638173f0e265-transport`
- runtime-input size: `222248960`
- runtime-input SHA-256: `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- release build: `#37` / run `37362499461` / success
- candidate SHA-256: `5eaf9e789663e76a5c65c9c4e55a84394c07dfd6b4f2395d0a19ef1effdbd9b5`
- installer SHA-256: `4500e3f699298ed7bad06be4070942339c1a04a233e68f9c6ae1cdf4dadf0179`
- payload SHA-256: `b3ba5c0528e0320c3c4fc9a64e33a96c4b2f34d35d3c7b69848ce93cc94e2693`
- approval: `#19` / success
- approval reference: `clientflow-1.3.31-seq-1232/aa9a57caa7a08fed17baaa0395a6638173f0e265`
- approved transport tag: `clientflow-1.3.31-1232-approved-transport`
- approved transport asset: `clientflow-approved-1.3.31-1232.tar`
- approved bundle size: `224174080`
- approved bundle SHA-256: `289489ce65501e8573d1406405cfd68b4e044ff8d0fc13b5f82d9a0ab72eb65f`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.31-seq-1232.tar`
- canonical publication result: `publication_exit_code=0`
- independent store re-read: exact size and SHA-256 verified,
  `IMMUTABLE_STORE_REREAD_VERIFIED` and `PUBLICATION_VERIFIED_SUCCESSFULLY`

The approved transport is transport-only. The exact approved bundle SHA-256,
its embedded approval/source identity and the no-replace Render store are the
release-byte authority.

## Catalog authority after this change

- `catalog_sequence = 1232`
- `latest_stable = 1.3.31`
- `default_install_version = 1.3.31`
- single selected release: `clientflow-1.3.31-seq-1232`
- `installable = true`
- `install_modes = ["fresh_install"]`
- `update_allowed = false`
- `rollback_allowed = false`
- no `min_current_version`
- controlled reboot remains required
- Ubuntu Desktop 26.04 LTS / `amd64` / GNOME Wayland platform preflight remains mandatory
- embedded runtime Python remains `3.13.14`

The catalog intentionally does not duplicate immutable bundle hashes, source
commit or approval metadata as selector fields. Those remain authority in the
published artifact and this promotion record.

The single-release retention policy means 1.3.30/1231 is no longer selected or
retained as catalog metadata after promotion. Its already published immutable
artifact remains untouched as historical evidence of the failed physical
acceptance that caused 1.3.31/1232.

## Fail-closed update boundary

The approved 1.3.31 bundle has `fresh_install` and `in_place_update` in its
technical bundle manifest because the release format supports both execution
paths. That is not sufficient evidence to authorize an update in the runtime
catalog.

The selector deliberately narrows the release to `install_modes=["fresh_install"]`
and `update_allowed=false`. `resolve_fresh_install_release()` therefore selects
1.3.31/1232, while `resolve_release("1.3.31")` fails closed with the explicit
physical-evidence block reason. No `min_current_version` is advertised because
no in-place update path is being authorized.

Authentic in-place update to 1.3.31 remains **UNVERIFIED**. No later release may
cite this catalog promotion itself as physical update evidence.

## Source-freeze evidence boundary

`CLIENTFLOW_1.3.31_1232_SOURCE_IDENTITY.md` and
`CLIENTFLOW_1.3.31_1232_SOURCE_FREEZE_CLOSURE.md` remain unchanged historical
records of the source-freeze gate. The later gate-order correction in the
canonical closure/procedure established approval/publication/promotion before
normal USB physical acceptance. This promotion record and `VALIDATION.txt`
carry the post-freeze release-chain evidence without rewriting immutable source
or approved bundle bytes.

No runtime, frontend, installer, database, dependency, media or release-format
source is changed by this promotion package. Only selector/evidence/tests and
the checksum manifest move forward.

## Post-deployment physical acceptance gate

After this selector change is merged, exact-commit CI is green and that exact
promotion commit is deployed, the live backend must be re-read to prove that
1.3.31/1232 is the active canonical fresh-install selection and resolves the
already published bundle at SHA-256
`289489ce65501e8573d1406405cfd68b4e044ff8d0fc13b5f82d9a0ab72eb65f`.

The next release gate is then a clean physical Ubuntu 26.04 fresh installation
through the canonical `Start ClientFlow.EXE` -> `01 Klient klargøring` ->
`02 Aktiver ClientFlow` -> pre-activation reboot -> backend approval/automatic
activation -> kiosk lockdown -> final reboot -> post-final-reboot acceptance
flow. The run must cover the frozen-domain regression set relevant to 1.3.31,
including kiosk lockdown and Nautilus/DING behaviour, Browser Guard/cookie
semantics, all five 10-second display/browser timings, service health,
Terminal, Remote Desktop WSS plus HTTPS fallback/file transfer/warm-grace
behaviour, Livestream HLS/multi-viewer/overview/warm-grace/resolution restart
behaviour, role-scoped health issues and the operator UI.

Physical acceptance is **PENDING** in this catalog-promotion package; source,
CI, build, approval, publication and catalog tests do not substitute for it.
