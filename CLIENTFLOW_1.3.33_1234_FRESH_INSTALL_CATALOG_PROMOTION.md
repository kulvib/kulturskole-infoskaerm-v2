# ClientFlow 1.3.33 / sequence 1234 — fresh-install-only catalog promotion

## Purpose

This change promotes the already approved, transported and immutably published
ClientFlow 1.3.33/1234 bytes as the canonical **fresh-install** target. It does
not claim or authorize in-place update compatibility.

The promotion follows the canonical release order for the normal USB/operator
path: source freeze -> source-qualified runtime inputs -> reproducible candidate
-> exact-byte approval -> immutable publication -> catalog promotion/redeploy ->
physical fresh-install acceptance. Approval, publication and promotion are
release-mechanics gates; they do not claim that physical acceptance has passed.

## Immutable authority chain

- release id: `clientflow-1.3.33-seq-1234`
- source commit: `a4faf2484125d3cd0dd089d2c0030f2e67519c5d`
- exact-source canonical CI: green before runtime-input transport dispatch
- runtime-input transport: `#19` / success
- runtime-input transport tag: `runtime-inputs-1234-a4faf2484125d3cd0dd089d2c0030f2e67519c5d-transport`
- runtime-input size: `222248960`
- runtime-input SHA-256: `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- release build: `#39` / run `37604394332` / success
- candidate SHA-256: `5d255e36fd6095bfaea983c323f036e50d438bd06f743230a11849f3ba5bebee`
- installer SHA-256: `477fabb5110fbc5204b2845a66ddd8c4ccb9f5e7ddd9eebb871ca5355095addb`
- payload SHA-256: `9561af060752999636e22b97b18cb60f387cec68959680b3aef6c27370511f66`
- approval: `#21` / success
- approval reference: `clientflow-1.3.33-seq-1234/a4faf2484125d3cd0dd089d2c0030f2e67519c5d`
- approved transport tag: `clientflow-1.3.33-1234-approved-transport`
- approved transport asset: `clientflow-approved-1.3.33-1234.tar`
- approved bundle size: `224174080`
- approved bundle SHA-256: `dd0222f8e8c9af2bc54b69ba0f2c0fe3c821077f1db59d219b79bd24a8065486`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.33-seq-1234.tar`
- canonical publication result: exact bundle size/SHA-256 accepted by `publish_clientflow_release.py`
- independent store re-read: exact size and SHA-256 verified and ended
  `IMMUTABLE_STORE_REREAD_VERIFIED`

The approved transport is transport-only. The exact approved bundle SHA-256,
its embedded approval/source identity and the no-replace Render store are the
release-byte authority.

## Catalog authority after this change

- `catalog_sequence = 1234`
- `latest_stable = 1.3.33`
- `default_install_version = 1.3.33`
- single selected release: `clientflow-1.3.33-seq-1234`
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

The single-release retention policy means 1.3.32/1233 is no longer selected or
retained as catalog metadata after promotion. Its already published immutable
artifact remains untouched as historical evidence of the failed physical
acceptance that led to the 1.3.33/1234 repair identity.

## Physical-acceptance repair scope carried by 1.3.33

The promoted release includes the already frozen repairs for the release blockers
observed during physical 1.3.32/1233 fresh-install acceptance:

- before first kiosk login, NetworkManager mutation attempts by `clientflow-kiosk`
  are denied with `polkit.Result.NO`, preventing an authentication dialog without
  granting the kiosk account network-administration authority;
- pre-reboot activation health no longer requires the conditional
  `clientflow-post-final-reboot-acceptance.service`; that service remains a
  mandatory later handoff/final-reboot acceptance gate;
- the hardened systemd sandbox keeps its broad restrictions while only the
  resolved kiosk `/run/user/<uid>` runtime path needed by GNOME/dconf is writable,
  allowing kiosk-lockdown convergence without disabling `ProtectHome` broadly;
- clock drift is projected against the durable server-side status-sample
  timestamp paired with the same `client_time_utc`, while older legacy snapshot
  shapes retain the compatible `reported_at` fallback.

The prior frontend Start/Stop kiosk-browser failure was observed while 1.3.32
was repeatedly entering activation then rolling back. It is therefore **not**
claimed fixed from source inspection alone and remains an explicit physical
retest item for this release.

## Fail-closed update boundary

The selector deliberately narrows the release to `install_modes=["fresh_install"]`
and `update_allowed=false`. No `min_current_version` is advertised because no
authentic in-place update path is being authorized.

Authentic in-place update to 1.3.33 remains **UNVERIFIED**. No later release may
cite this catalog promotion itself as physical update evidence.

## Source-freeze evidence boundary

`CLIENTFLOW_1.3.33_1234_SOURCE_IDENTITY.md` and
`CLIENTFLOW_1.3.33_1234_SOURCE_FREEZE_CLOSURE.md` remain unchanged historical
records of the source-freeze gate. They correctly describe the state at freeze
time before build, approval, immutable publication and catalog promotion. This
promotion record and `VALIDATION.txt` carry the later release-chain evidence
without rewriting those historical records or the immutable approved bundle.

No ClientFlow runtime, frontend application source, installer, backend/database
schema, dependency, transport or media source is changed by this promotion
package.

## Post-deployment physical acceptance gate

After this selector change is merged, exact-commit CI is green and that exact
promotion commit is deployed, the live backend must be independently re-read to
prove that 1.3.33/1234 is the active canonical fresh-install selection and that
its resolver reaches the already published immutable artifact at SHA-256
`dd0222f8e8c9af2bc54b69ba0f2c0fe3c821077f1db59d219b79bd24a8065486`.

The next release gate is then a clean physical Ubuntu 26.04 fresh installation
through the canonical `Start ClientFlow.EXE` -> `01 Klient klargøring` -> first
kiosk login -> `02 Aktiver ClientFlow` -> pre-activation reboot -> backend
approval/automatic activation -> converged kiosk lockdown -> final reboot ->
post-final-reboot acceptance flow.

The run must explicitly prove the absence of the NetworkManager password popup,
a stable approved state, completed local GUI transition, credible clock drift,
frontend Start/Stop kiosk-browser commands, Control Room live state, Browser
Guard, Terminal, Remote Desktop, Livestream and all five 10-second display/browser
contracts, together with the remaining relevant frozen-domain acceptance set.

Physical acceptance is **PENDING** in this catalog-promotion package; source,
CI, build, approval, publication and catalog tests do not substitute for it.
