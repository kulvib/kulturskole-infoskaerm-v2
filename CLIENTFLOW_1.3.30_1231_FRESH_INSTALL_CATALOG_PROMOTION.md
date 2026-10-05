# ClientFlow 1.3.30 / sequence 1231 — fresh-install-only catalog promotion

## Purpose

This change promotes the already approved, transported and immutably published
ClientFlow 1.3.30/1231 bytes as the canonical **fresh-install** target. It does
not claim or authorize in-place update compatibility.

The catalog promotion is deliberately separate from source freeze, build,
approval and immutable publication. The canonical release procedure requires
the exact approved bytes to exist in the backend artifact store and to survive
an independent re-read before selector authority moves. That prerequisite is
now satisfied.

## Immutable authority chain

- release id: `clientflow-1.3.30-seq-1231`
- source commit: `6995280649c68bbd201dee73edde7d6a1f71eaa5`
- exact-source CI: `#1219` / run `37210696042` / success
- runtime-input transport: `#14` / run `37212319478` / success
- runtime-input transport tag: `runtime-inputs-1231-6995280649c68bbd201dee73edde7d6a1f71eaa5-transport`
- runtime-input size: `222248960`
- runtime-input SHA-256: `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- release build: `#35` / run `37230708535` / success
- candidate SHA-256: `2491c1a15a182e4836b0458e812b304ec7c01d6f897e209b2a49d401930cc8e0`
- installer SHA-256: `56d929b290e80e7e2ab6dbfe3dcbfc74aaa097e70fb2e1c81062bc06703a820d`
- payload SHA-256: `90d79f760c29bbb3d7c4c0c1af56b1451626490a14d502d2821f74d5bf509fed`
- approval: `#18` / run `37267974054` / success
- approval reference: `clientflow-1.3.30-seq-1231/6995280649c68bbd201dee73edde7d6a1f71eaa5`
- approved transport tag: `clientflow-1.3.30-1231-approved-transport`
- approved transport asset: `clientflow-approved-1.3.30-1231.tar`
- approved bundle size: `224174080`
- approved bundle SHA-256: `b3fbe2530907d86e581704a58819c01f17d8ca2f8842a0d2f6e35f9bb9138cd7`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.30-seq-1231.tar`
- immutable publication result: `publish_exit_code=0`
- independent store re-read: exact size and SHA-256 verified, `PUBLICATION_VERIFIED_OK`

The approved transport is transport-only. The exact approved bundle SHA-256,
its embedded approval/source identity and the no-replace Render store are the
release-byte authority.

## Catalog authority after this change

- `catalog_sequence = 1231`
- `latest_stable = 1.3.30`
- `default_install_version = 1.3.30`
- single selected release: `clientflow-1.3.30-seq-1231`
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

The single-release retention policy means 1.3.29/1230 is no longer selected or
retained as catalog metadata after promotion. Its already published immutable
artifact is not modified by this selector change.

## Fail-closed update boundary

The approved 1.3.30 bundle has `fresh_install` and `in_place_update` in its
technical bundle manifest because the release format supports both execution
paths. That is not sufficient evidence to authorize an update in the runtime
catalog.

The selector deliberately narrows the release to `install_modes=["fresh_install"]`
and `update_allowed=false`. `resolve_fresh_install_release()` therefore selects
1.3.30/1231, while `resolve_release("1.3.30")` fails closed with the explicit
physical-evidence block reason. No `min_current_version` is advertised because
no in-place update path is being authorized.

Authentic in-place update to 1.3.30 remains **UNVERIFIED**. No later release may
cite this catalog promotion itself as physical update evidence.

## Source-freeze evidence boundary

`CLIENTFLOW_1.3.30_1231_SOURCE_IDENTITY.md` and
`CLIENTFLOW_1.3.30_1231_SOURCE_FREEZE_CLOSURE.md` remain unchanged historical
records of the earlier source-freeze gate. Their pre-build/pre-publication
statements are not rewritten after the fact. This promotion record and
`VALIDATION.txt` carry the later release-chain evidence.

No runtime, frontend, installer, database, dependency, media or release-format
source is changed by this promotion package. Only selector/evidence/tests and
the checksum manifest move forward.

## Post-deployment physical acceptance gate

After this selector change is merged, exact-commit CI is green and that exact
promotion commit is deployed, the live backend must be re-read to prove that
1.3.30/1231 is the active canonical fresh-install selection and resolves the
already published bundle at SHA-256 `b3fbe2530907d86e581704a58819c01f17d8ca2f8842a0d2f6e35f9bb9138cd7`.

The next release gate is then a clean physical Ubuntu 26.04 fresh installation
through the canonical `01 Klient klargøring` -> `02 Aktiver ClientFlow` ->
backend approval -> post-final-reboot acceptance flow. The run must cover the
frozen-domain regression set relevant to 1.3.30, including kiosk lockdown and
Nautilus/DING behaviour, Browser Guard/cookie semantics, all five 10-second
display/browser timings, service health, Terminal, Remote Desktop WSS plus
HTTPS fallback/file transfer/warm-grace behaviour, Livestream HLS/multi-viewer/
overview/warm-grace/resolution restart behaviour, role-scoped health issues and
the operator UI changes.

Physical acceptance is **PENDING** in this catalog-promotion package; source,
CI, build, approval, publication and catalog tests do not substitute for it.
