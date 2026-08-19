# ClientFlow 1.2 canonical release procedure

This procedure describes the current v2 source/release contract. Historical multi-version installers and signed catalog flows are not part of the canonical repository.

## 1. Inputs

Canonical source:

- `client/VERSION`
- `client/release/release-input.json`
- `client/runtime/`
- `client/systemd/`
- `client/sysusers.d/`
- `client/tmpfiles.d/`
- `client/config-examples/`
- `client/libexec/`
- `client/release/lib/clientflow_release/`

Offline runtime inputs are supplied separately through `--runtime-inputs`. They must contain the validated Python runtime and dependency wheelhouse. The ClientFlow runtime wheel itself is always rebuilt from `client/runtime/`; a supplied stale ClientFlow wheel is removed before packaging.

## 2. Build a release candidate

Use a clean reviewed commit. Set `SOURCE_DATE_EPOCH` from the source commit and build:

```bash
SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" \
python scripts/build_clientflow_release.py \
  --repo . \
  --runtime-inputs /secure/path/runtime-inputs \
  --output-dir ./build/clientflow-1.2.0
```

A normal candidate is always `deployable: false`. The builder verifies source identity, manifest structure, payload integrity and offline runtime completeness.

Record the exact candidate SHA-256:

```bash
sha256sum ./build/clientflow-1.2.0/clientflow-1.2.0-seq-1200-candidate.tar
```

## 3. Approve one exact candidate

Approval uses no release signing key. It is an explicit gate bound to the exact candidate hash, exact source commit and an approval reference:

```bash
python scripts/approve_clientflow_release.py \
  ./build/clientflow-1.2.0/clientflow-1.2.0-seq-1200-candidate.tar \
  --output ./build/clientflow-1.2.0/clientflow-1.2.0-seq-1200-approved.tar \
  --expected-candidate-sha256 <EXACT_CANDIDATE_SHA256> \
  --expected-source-commit <FULL_40_CHARACTER_GIT_SHA> \
  --approval-reference <CHANGE_OR_RELEASE_REFERENCE> \
  --approve-release
```

Only the approved output may have `deployable: true`.

Record the SHA-256 of the approved bundle. That hash is the transport/install binding used by both verifier and installer.

## 4. Verify the approved bundle

Use the generated `clientflow-installer` together with the exact approved bundle hash:

```bash
clientflow-installer verify \
  --bundle ./build/clientflow-1.2.0/clientflow-1.2.0-seq-1200-approved.tar \
  --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256>
```

Verification must succeed before a physical installation is considered.

## 5. Fresh installation

Installation is for a clean Ubuntu Desktop 26.04 `amd64` client with an existing unprivileged kiosk user and a valid one-time enrollment code:

```bash
sudo clientflow-installer install \
  --bundle ./build/clientflow-1.2.0/clientflow-1.2.0-seq-1200-approved.tar \
  --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256> \
  --backend-url https://<backend-origin> \
  --enrollment-code <one-time-code> \
  --kiosk-user <kiosk-user>
```

The fresh installer provisions six domain credentials, the client system encryption identity, immutable release files and rendered systemd definitions. It stops at `pending_manual_activation`.

## 6. Manual activation

Activation is explicit:

```bash
clientflow-installer activate \
  --release-id clientflow-1.2.0-seq-1200 \
  --approval-reference <CHANGE_OR_RELEASE_REFERENCE>
```

Activation switches `/opt/clientflow/active`, applies managed definitions and runs health checks. Failure triggers the transaction's rollback behavior.

## 7. Validation before deployment

At minimum:

```bash
python -m compileall -q backend/service1 backend/migrations client/runtime client/release/lib scripts
python -m pytest -q backend/tests/test_*source*.py
```

A release/install change is not accepted as physically validated until the relevant Ubuntu installation/update and frozen-domain regressions have been run.
