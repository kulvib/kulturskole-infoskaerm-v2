# ClientFlow 1.3 canonical release procedure

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

`client/VERSION` is the only manually maintained product-version value. The runtime wheel derives its PEP 621 version dynamically from that same authority, while `release_sequence` remains the separate monotonic anti-rollback identity component. For the current canonical bootstrap release these values are `1.3.0` and `1201`, producing `clientflow-1.3.0-seq-1201`.

## 2. Build a release candidate

Use a clean reviewed commit. Set `SOURCE_DATE_EPOCH` from the source commit and build:

```bash
SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" \
python scripts/build_clientflow_release.py \
  --repo . \
  --runtime-inputs /secure/path/runtime-inputs \
  --output-dir ./build/clientflow-1.3.0
```

A normal candidate is always `deployable: false`. The builder verifies source identity, manifest structure, payload integrity and offline runtime completeness.

Record the exact candidate and fresh-installer SHA-256 values. The candidate manifest also binds the fresh installer by file name, size and SHA-256:

```bash
sha256sum \
  ./build/clientflow-1.3.0/clientflow-1.3.0-seq-1201-candidate.tar \
  ./build/clientflow-1.3.0/clientflow-installer-1.3.0.pyz
```

## 3. Approve one exact candidate

Approval uses no release signing key. It is an explicit gate bound to the exact candidate hash, exact source commit and an approval reference:

```bash
python scripts/approve_clientflow_release.py \
  ./build/clientflow-1.3.0/clientflow-1.3.0-seq-1201-candidate.tar \
  --output ./build/clientflow-1.3.0/clientflow-1.3.0-seq-1201-approved.tar \
  --expected-candidate-sha256 <EXACT_CANDIDATE_SHA256> \
  --installer ./build/clientflow-1.3.0/clientflow-installer-1.3.0.pyz \
  --expected-installer-sha256 <EXACT_INSTALLER_SHA256> \
  --expected-source-commit <FULL_40_CHARACTER_GIT_SHA> \
  --approval-reference <CHANGE_OR_RELEASE_REFERENCE> \
  --approve-release
```

Only the approved output may have `deployable: true`. The approval gate opens the candidate once with no-follow semantics and keeps that exact file identity pinned while whole-bundle SHA-256, manifest/payload, runtime preflight and promotion are evaluated. Replacing the candidate pathname during approval cannot change the bytes being approved. The approved manifest preserves the exact `fresh_installer` descriptor from the approved candidate.

Record the SHA-256 of the approved bundle. That hash is the external trust anchor for the physical handoff.

## 4. Verify the fresh-install handoff before executing installer code

The installer runs with root privileges and must therefore be verified **before it is executed**, using only the already-trusted approved bundle hash plus host tools. First verify the approved bundle bytes, then read the installer descriptor from that verified bundle and verify the installer file:

```bash
BUNDLE=./build/clientflow-1.3.0/clientflow-1.3.0-seq-1201-approved.tar
INSTALLER=./build/clientflow-1.3.0/clientflow-installer-1.3.0.pyz
APPROVED_BUNDLE_SHA256=<APPROVED_BUNDLE_SHA256>

printf '%s  %s\n' "$APPROVED_BUNDLE_SHA256" "$BUNDLE" | /usr/bin/sha256sum --check --strict -

read -r EXPECTED_INSTALLER_FILE EXPECTED_INSTALLER_SIZE EXPECTED_INSTALLER_SHA256 < <(
  /usr/bin/tar -xOf "$BUNDLE" manifest.json |
  /usr/bin/python3 -I -c 'import json,sys; x=json.load(sys.stdin)["fresh_installer"]; print(x["file"], x["size"], x["sha256"])'
)

test "$(/usr/bin/basename "$INSTALLER")" = "$EXPECTED_INSTALLER_FILE"
test "$(/usr/bin/stat -c %s "$INSTALLER")" -eq "$EXPECTED_INSTALLER_SIZE"
printf '%s  %s\n' "$EXPECTED_INSTALLER_SHA256" "$INSTALLER" | /usr/bin/sha256sum --check --strict -
```

No installer command may run if any of those checks fails. This closes the root-bootstrap trust boundary: the approved bundle bytes bind the exact executable installer bytes.

After that external verification, use the now-verified installer together with the exact approved bundle hash:

```bash
/usr/bin/python3 -I "$INSTALLER" verify \
  --bundle "$BUNDLE" \
  --expected-bundle-sha256 "$APPROVED_BUNDLE_SHA256"
```

Verification must succeed before a physical installation is considered.

## 5. Fresh installation

Installation is for a clean Ubuntu Desktop 26.04 `amd64` client with an existing unprivileged kiosk user and a valid one-time enrollment code:

```bash
sudo /usr/bin/python3 -I "$INSTALLER" install \
  --bundle "$BUNDLE" \
  --expected-bundle-sha256 "$APPROVED_BUNDLE_SHA256" \
  --backend-url https://<backend-origin> \
  --enrollment-code <one-time-code> \
  --kiosk-user <kiosk-user>
```

The fresh installer provisions six domain credentials, the client system encryption identity, immutable release files and rendered systemd definitions. It stops at `pending_manual_activation`.

## 6. Manual activation

Activation is explicit:

```bash
sudo /usr/bin/python3 -I "$INSTALLER" activate \
  --release-id clientflow-1.3.0-seq-1201 \
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
