# ClientFlow 1.3.34 / sequence 1235 — fresh-install-only catalog promotion

## Scope and release boundary

Promote the already approved, immutably published, and independently verified
ClientFlow **1.3.34 / 1235** as the **only canonical fresh-install selection**.
This is a catalog policy and regression-evidence change, not a rebuild,
re-approval, in-place update authorization, or physical-acceptance certificate.
The previous 1.3.33/1234 catalog selection is superseded only after this
promotion is merged, passes exact-commit CI, and is deployed to Render.
The previous immutable approved bundle remains untouched in the artifact store.

## Immutable release authority — completed before catalog promotion

- Canonical release ID: `clientflow-1.3.34-seq-1235`
- Source commit: `51e93dad8b1cffd43e03845ae0a7e2472d955a65`
- Exact-source GitHub CI: green prior to release/build approval
- Runtime-input transport: source-qualified; 222248960 bytes; SHA-256 `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- Independent reproducible release builds: successful, byte-identical; Ubuntu 26.04 executable-candidate gate passed
- Candidate SHA-256: `436b454fadf35ce7ae417ce82d40de4370aab2f466da463d80269255a0770955`
- Fresh installer SHA-256: `042a55a3215d704cdb4c7de80abfdd5baeefec7f7bdac7ada80538bec423695c`
- Canonical ClientFlow release approval: successful GitHub Actions `release-approve.yml`, exact source/candidate/installer bound
- Approval reference: `clientflow-1.3.34-seq-1235/51e93dad8b1cffd43e03845ae0a7e2472d955a65/manual-approval-20261008`
- Approved transport tag: `clientflow-1.3.34-1235-approved-transport` (GitHub pre-release; transport only)
- Transport asset: `clientflow-approved.tar`; 224174080 bytes; SHA-256 `7b069011ca94dd90eefdb4248b0029c8e6d98787bdab0a7678a700f1a5bf4759`
- Immutable Render store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.34-seq-1235.tar`
- Canonical publication: `publish_clientflow_release.py` completed with exact approved SHA-256 and approval reference
- Independent read-back: manifest source, release ID, sequence and approval identity verified; SHA-256 and size verified; `IMMUTABLE_STORE_REREAD_VERIFIED=PASS`
- Store capacity after publication: 530 MB available; older 1.3.30–1.3.32 TARs intentionally cleaned up after inventory and operator confirmation of zero active clients; retained 1.3.33 and 1.3.34 published TARs

The approved transport is not a promotion authority by itself: the exact approved
bundle SHA-256, the approval record, and the no-replace immutable Render store
form the artifact authority. The catalog intentionally does not duplicate
source SHA-256, candidate SHA-256 or approval metadata as selector fields.

## Promoted selector policy

- `catalog_sequence = 1235`
- `latest_stable = 1.3.34`
- `default_install_version = 1.3.34`
- The **only** `releases[]` entry is `clientflow-1.3.34-seq-1235`
- `installable = true`, `status = stable`
- `install_modes = ["fresh_install"]`
- `update_allowed = false` and `rollback_allowed = false`
- No `min_current_version`; no implicit latest/stable update alias
- `requires_reboot = true` and `requires_platform_preflight = true`
- Ubuntu Desktop **26.04** LTS, **amd64**, GNOME/Wayland
- Embedded runtime Python remains **3.13.14**
- One-installable-version retention policy unchanged; blocked and historically rejected sequences are not reintroduced

Physical repair scope is inherited from the frozen 1.3.34 source/build:
Control Room realtime capability authorization, exact OS-update command identity,
kiosk lockdown desired-vs-observed state, supervised kiosk GUI, and the
Ubuntu/kiosk physical blockers addressed in the frozen candidate. **These
source gates do not prove a successful physical fresh installation.**

## Evidence and historical boundaries

The prior `CLIENTFLOW_1.3.34_1235_PHYSICAL_ACCEPTANCE_BLOCKERS_STAGE1.md`
remains a truthful historical stage-1 snapshot (it was not yet built or approved
at that point). The 1.3.33 source-freeze and catalog-promotion evidence also
remains unchanged. This record and the appended `VALIDATION.txt` section
record the subsequent completed release-chain and promotion preparation.

No runtime, frontend application source, installer payload, backend database
schema, dependency locks, transport workflow, or immutable release TAR is changed
by this promotion package.

## Exact-commit CI, deployment and physical acceptance

1. Merge this selector/evidence/tests change; require full green GitHub CI on
   **the exact promotion commit** (different from the frozen release source commit).
2. Redeploy that exact promotion commit on `planiq-display-v2-backend`.
3. Independently re-read live catalog (`1.3.34/1235`, fresh-install-only) and
   resolve the fresh-install selection to `clientflow-1.3.34-seq-1235.tar` in
   `/var/data/clientflow-release-artifacts/store`, proving SHA-256
   `7b069011ca94dd90eefdb4248b0029c8e6d98787bdab0a7678a700f1a5bf4759`. Also confirm old approved 1.3.33 bytes remain untouched.
4. Manufacture and byte-verify a fresh canonical USB and perform the complete
   clean Ubuntu 26.04 physical factory/activation acceptance.
5. Explicitly retest the previous physical blockers (OS updates, kiosk lockdown,
   realtime 401s, GUI close protection and lifecycle, command correlation),
   alongside NetworkManager, approval/reboot sequencing, Control Room, Browser
   Guard, Terminal, Remote Desktop, Livestream, and all five 10-second contracts.

Physical acceptance is **PENDING**. In-place update and rollback are **NOT
AUTHORIZED** by this release promotion. No clients are claimed accepted by
source, CI, release approval, publication or backend smoke testing alone.
