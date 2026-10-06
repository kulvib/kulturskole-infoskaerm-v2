# ClientFlow 1.3.32 / sequence 1233 — fresh-install-only catalog promotion

## Purpose

This change promotes the already approved, transported and immutably published
ClientFlow 1.3.32/1233 bytes as the canonical **fresh-install** target. It does
not claim or authorize in-place update compatibility.

The promotion follows the canonical release order for the normal USB/operator
path: source freeze -> source-qualified runtime inputs -> reproducible candidate
-> exact-byte approval -> immutable publication -> catalog promotion/redeploy ->
physical fresh-install acceptance. Approval, publication and promotion are
release-mechanics gates; they do not claim that physical acceptance has passed.

## Immutable authority chain

- release id: `clientflow-1.3.32-seq-1233`
- source commit: `82a8ea671b6427017c6db5ca83096f7ebcc69306`
- exact-source canonical CI: green before runtime-input transport dispatch
- runtime-input transport: `#17` / success
- runtime-input transport tag: `runtime-inputs-1233-82a8ea671b6427017c6db5ca83096f7ebcc69306-transport`
- runtime-input size: `222248960`
- runtime-input SHA-256: `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- release build: `#38` / run `37512143962` / success
- candidate SHA-256: `0f3f3c1fcd1f6d82417995a65ece421dc2e5ce59af4431fad03bdbb387afb09b`
- installer SHA-256: `157c7682b7c75477630e465c208b4614b326c98e16620a8f5e521943ae5c82dd`
- payload SHA-256: `4b6714c01066a0b6bec96cc7773c06e9d88225a11905e4d3481bac0d83ff24f8`
- approval: `#20` / success
- approval reference: `clientflow-1.3.32-seq-1233/82a8ea671b6427017c6db5ca83096f7ebcc69306`
- approved transport tag: `clientflow-1.3.32-1233-approved-transport`
- approved transport asset: `clientflow-approved-1.3.32-1233.tar`
- approved bundle size: `224174080`
- approved bundle SHA-256: `93a56a360e4a74d0eb75ea77bc4cb2a592266d89a7daea9981391efc50252b35`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.32-seq-1233.tar`
- canonical publication result: `publication_exit_code=0`
- independent store re-read: exact size and SHA-256 verified,
  `IMMUTABLE_STORE_REREAD_VERIFIED` and `PUBLICATION_VERIFIED_SUCCESSFULLY`

The approved transport is transport-only. The exact approved bundle SHA-256,
its embedded approval/source identity and the no-replace Render store are the
release-byte authority.

## Catalog authority after this change

- `catalog_sequence = 1233`
- `latest_stable = 1.3.32`
- `default_install_version = 1.3.32`
- single selected release: `clientflow-1.3.32-seq-1233`
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

The single-release retention policy means 1.3.31/1232 is no longer selected or
retained as catalog metadata after promotion. Its already published immutable
artifact remains untouched as historical evidence of the physical acceptance
run that exposed the runtime/convergence defects repaired by 1.3.32/1233.

## Physical-acceptance repair scope carried by 1.3.32

The promoted release includes the already frozen repairs for the release blockers
observed during physical 1.3.31/1232 fresh-install acceptance:

- clock drift is projected from one coherent client/server status sample rather
  than from the age of the durable status row;
- post-final-reboot acceptance reasserts the GNOME kiosk-lockdown baseline only
  after the canonical seat0 Wayland session and user D-Bus are verified, while
  retaining fail-closed enforcement if convergence cannot be proven;
- the local GUI represents the approved first-activation handoff explicitly
  instead of presenting stale backend `pending` / `ClientFlow update: unknown`
  as a steady state;
- Control Room realtime wakeups arriving during an in-flight status snapshot
  force a subsequent snapshot without shortening the normal 60-second idle poll;
- transient refresh/network failures no longer cause an unauthoritative logout,
  while refresh-token rotation/replay protection remains intact and Livestream
  control/heartbeat traffic uses the shared refresh-aware path;
- Livestream Overview exposes fullscreen and measured playback delay and keeps
  signal-timeout recovery bounded by the existing control-plane rules.

## Fail-closed update boundary

The approved 1.3.32 bundle has `fresh_install` and `in_place_update` in its
technical bundle manifest because the release format supports both execution
paths. That is not sufficient evidence to authorize an update in the runtime
catalog.

The selector deliberately narrows the release to `install_modes=["fresh_install"]`
and `update_allowed=false`. `resolve_fresh_install_release()` therefore selects
1.3.32/1233, while `resolve_release("1.3.32")` fails closed with the explicit
physical-evidence block reason. No `min_current_version` is advertised because
no in-place update path is being authorized.

Authentic in-place update to 1.3.32 remains **UNVERIFIED**. No later release may
cite this catalog promotion itself as physical update evidence.

## Source-freeze evidence boundary

`CLIENTFLOW_1.3.32_1233_SOURCE_IDENTITY.md` and
`CLIENTFLOW_1.3.32_1233_SOURCE_FREEZE_CLOSURE.md` remain unchanged historical
records of the source-freeze gate. They correctly describe the state at freeze
time before build, approval, publication and catalog promotion. This promotion
record and `VALIDATION.txt` carry the later release-chain evidence without
rewriting those historical records or the immutable approved bundle bytes.

No ClientFlow runtime, frontend application source, installer, backend/database,
dependency, transport or media source is changed by this promotion package.

## Post-deployment physical acceptance gate

After this selector change is merged, exact-commit CI is green and that exact
promotion commit is deployed, the live backend must be re-read to prove that
1.3.32/1233 is the active canonical fresh-install selection and resolves the
already published bundle at SHA-256
`93a56a360e4a74d0eb75ea77bc4cb2a592266d89a7daea9981391efc50252b35`.

The next release gate is then a clean physical Ubuntu 26.04 fresh installation
through the canonical `Start ClientFlow.EXE` -> `01 Klient klargøring` ->
`02 Aktiver ClientFlow` -> pre-activation reboot -> backend approval/automatic
activation -> converged kiosk lockdown -> final reboot -> post-final-reboot
acceptance flow. The run must repeat the relevant frozen-domain regression set,
including clock integrity, kiosk Wayland/seat0 and sudo/admin separation,
GNOME/DING/Nautilus lockdown, Browser Guard/cookies, all five 10-second
display/browser contracts, service health, Terminal, Remote Desktop WSS plus
HTTPS fallback/input/file transfer/warm grace, Livestream HLS/multiview/overview
fullscreen/delay/signal-timeout recovery/warm grace/resolution restart,
firewall/fallback/reconnect/performance, realtime client-list status, frontend
session longevity and the operator/local GUI.

Physical acceptance is **PENDING** in this catalog-promotion package; source,
CI, build, approval, publication and catalog tests do not substitute for it.
