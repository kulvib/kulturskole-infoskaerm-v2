# ClientFlow legacy 1.1.19 full capability / executable parity gate

Status: source closure for **L119-08**. Physical acceptance remains deferred until the next approved Ubuntu 26.04 clean-install verification.

## Defect / inconsistency

The previous V2 legacy gate treated 46 Python filenames as the acceptance boundary and only required that each row named an existing V2 replacement path.

## Trigger

A source change removes or breaks legacy installer/factory/systemd/desktop/GUI/recovery/session behavior while leaving the named replacement file present.

## Consequence

CI can stay green even though a fresh Ubuntu 26.04 client is functionally below the physically proven 1.1.19 acceptance level. The next physical clean install becomes discovery rather than verification.

## Evidence

The immutable legacy 1.1.19 reference used for this gate is pinned as:

- installer ZIP SHA256: `61dc8a417aaa32f4eabc7430a2af886933473142cebcdcbe8f1064a318941e80`
- installer ZIP size: `528568`
- embedded payload SHA256: `d490dd8f0effccc58e8d5687ae95d0821bf2747d4f131a2ee3a9c3088c1ec331`
- embedded payload size: `482779`
- installed payload files: **166**
- non-payload installer/factory surface files: **11**
- total exact inventory entries: **177**

The old `client/legacy-client-parity.json` recorded only 46 Python files and `scripts/tests/test_clientflow_legacy_client_parity.py` only proved disposition text + replacement-file existence.

## Root cause

Parity was modeled as **filename replacement**, not **functional capability + executable proof**.

## Fix

`client/legacy-client-parity.json` is schema 2 and now contains:

1. the immutable legacy installer/payload identities;
2. an exact path/size/SHA256 inventory of all 177 installer+payload surface entries;
3. one primary capability disposition for every inventory entry;
4. a functional capability matrix for:
   - fresh install/factory/enrollment;
   - dedicated human accounts/session baseline;
   - network/name/locality/bootstrap cleanup;
   - Display/browser/calendar;
   - local GUI/recovery/support;
   - time/session/quick-settings/popup policy;
   - local power/System/OS update;
   - whole-bundle update/rollback/pre-first-activation repair;
   - Status/diagnostics/reconnect;
   - Frozen Livestream;
   - Frozen Terminal;
   - Frozen Remote Desktop;
   - runtime state/config/dependency materialization;
5. explicit V2 replacement paths;
6. explicit Python, frontend and Ubuntu-host proofs;
7. a requirement that every capability has at least one non-source-only executable/behavior/host proof.

`scripts/verify_clientflow_legacy119_capability_gate.py` validates the complete matrix and can execute the proof surface by CI scope:

- `--scope python`: reruns the curated Python behavior/integration proofs after the complete backend/scripts suite;
- `--scope frontend`: reruns the curated Node behavior proofs after the complete frontend suite;
- `--scope host`: runs the host capability proof on exact Ubuntu 26.04 after the existing destructive preclaim APT/curl recovery and platform-install gates;
- the existing destructive preclaim bootstrap proof remains separately wired in the Ubuntu 26.04 job and is required by the manifest as an external host proof.

This does **not** make legacy architecture canonical. The manifest records functional disposition only. V2 release authority, unique credentials, domain isolation, immutable whole-bundle authority and backend authorization remain authoritative.

## Affected files

- `client/legacy-client-parity.json`
- `scripts/verify_clientflow_legacy119_capability_gate.py`
- `scripts/tests/test_clientflow_legacy_client_parity.py`
- `.github/workflows/ci.yml`
- `CLIENTFLOW_LEGACY_119_PARITY_REVIEW.md`
- this document

No runtime, installer transaction, migration, backend route, frontend product code or systemd unit is changed by this batch.

## Frozen risk

Livestream, Terminal and Remote Desktop are represented as explicit **frozen implemented capabilities**. This batch does not modify any of their agent, broker, credential, protocol, capture, systemd or frontend runtime files.

Their gate proofs are read-only compatibility/isolation tests plus existing behavior tests. A parity-gate failure does not authorize changing a Frozen domain without a separately documented defect/root cause.

## Regression / release gate

The source is not ready for release merely because this manifest validates. CI must pass all ordinary suites **and** the three scoped parity-gate executions.

After merge, the next action is a fresh read-only production-readiness review. If no A/B/required-C blockers remain, the sequence is then:

`new source identity as required → reproducible build → manual approval → immutable publish to canonical Render store → catalog promotion → physical Ubuntu 26.04 clean-install verification`.
