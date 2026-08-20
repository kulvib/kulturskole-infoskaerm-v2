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
  --expected-installer-sha256 <EXACT_INSTALLER_SHA256> \
  --expected-source-commit <FULL_40_CHARACTER_GIT_SHA> \
  --approval-reference <CHANGE_OR_RELEASE_REFERENCE> \
  --approve-release
```

Only the approved output may have `deployable: true`. The approval gate opens the candidate once with no-follow semantics and keeps that exact file identity pinned while whole-bundle SHA-256, manifest/payload, the embedded fresh-installer member, runtime preflight and promotion are evaluated. Replacing the candidate pathname during approval cannot change the bytes being approved. Schema 8 requires the fresh installer to be physically embedded in the same bundle and to match the exact `fresh_installer` descriptor.

Record the SHA-256 of the approved bundle. That hash is the external trust anchor for the physical handoff.

## 4. Materialize a pinned fresh-install bootstrap before executing installer code

The approved bundle SHA-256 is the external trust anchor. The fresh installer is **not** a second loose trust artifact: schema 8 embeds its exact bytes inside the approved bundle.

The physical handoff must therefore keep one concrete bundle file identity open while it hashes that file, reads `manifest.json`, and extracts the embedded installer. The extracted installer and an exact copy of the approved bundle are materialized into a new root-owned private directory under `/run`; installer code is first executed from that private copy, never from a user-writable build/download pathname.

Run the following as one uninterrupted shell block. No ClientFlow installer code runs inside the bootstrap block; it uses only host `bash`, `sha256sum`, `tar`, `python3`, `stat`, `cmp`, and filesystem primitives:

```bash
BUNDLE=./build/clientflow-1.3.0/clientflow-1.3.0-seq-1201-approved.tar
APPROVED_BUNDLE_SHA256=<APPROVED_BUNDLE_SHA256>

BOOTSTRAP_DIR="$(
  sudo /usr/bin/mktemp -d /run/clientflow-fresh-install.XXXXXXXX
)"
sudo /usr/bin/chown root:root "$BOOTSTRAP_DIR"
sudo /usr/bin/chmod 0700 "$BOOTSTRAP_DIR"

sudo /usr/bin/bash -s -- \
  "$BUNDLE" \
  "$APPROVED_BUNDLE_SHA256" \
  "$BOOTSTRAP_DIR" <<'CLIENTFLOW_BOOTSTRAP'
set -euo pipefail

BUNDLE_PATH=$1
EXPECTED_BUNDLE_SHA256=$2
BOOTSTRAP_DIR=$3

# One root process opens the untrusted pathname exactly once. Whatever bytes
# were opened must match the externally approved whole-bundle SHA-256.
exec {BUNDLE_FD}<"$BUNDLE_PATH"
BUNDLE_FD_PATH="/proc/$$/fd/$BUNDLE_FD"

test "$(/usr/bin/stat -Lc %F "$BUNDLE_FD_PATH")" = "regular file"
printf '%s  %s\n' \
  "$EXPECTED_BUNDLE_SHA256" \
  "$BUNDLE_FD_PATH" |
  /usr/bin/sha256sum --check --strict -

read -r INSTALLER_FILE INSTALLER_SIZE INSTALLER_SHA256 < <(
  /usr/bin/tar -xOf "$BUNDLE_FD_PATH" manifest.json |
  /usr/bin/python3 -I -c \
    'import json,sys; x=json.load(sys.stdin)["fresh_installer"]; print(x["file"], x["size"], x["sha256"])'
)

case "$INSTALLER_FILE" in
  clientflow-installer-*.pyz) ;;
  *) echo "Ugyldigt fresh_installer-filnavn" >&2; exit 1 ;;
esac
case "$INSTALLER_SIZE" in
  ''|*[!0-9]*) echo "Ugyldig fresh_installer-størrelse" >&2; exit 1 ;;
esac
case "$INSTALLER_SHA256" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*)
    test "${#INSTALLER_SHA256}" -eq 64
    ;;
  *) echo "Ugyldig fresh_installer-SHA-256" >&2; exit 1 ;;
esac

PRIVATE_BUNDLE="$BOOTSTRAP_DIR/clientflow-approved.tar"
PRIVATE_INSTALLER="$BOOTSTRAP_DIR/$INSTALLER_FILE"
TMP_BUNDLE="$BOOTSTRAP_DIR/.bundle.tmp"
TMP_INSTALLER="$BOOTSTRAP_DIR/.installer.tmp"

# Copy from the same pinned bundle identity that passed the external hash gate.
# Extract the installer from that same open bundle, never from a second path.
cat "$BUNDLE_FD_PATH" >"$TMP_BUNDLE"
/usr/bin/tar -xOf "$BUNDLE_FD_PATH" "$INSTALLER_FILE" >"$TMP_INSTALLER"

/usr/bin/chown root:root "$TMP_BUNDLE" "$TMP_INSTALLER"
/usr/bin/chmod 0400 "$TMP_BUNDLE"
/usr/bin/chmod 0500 "$TMP_INSTALLER"

test "$(/usr/bin/stat -Lc %s "$TMP_INSTALLER")" -eq "$INSTALLER_SIZE"
printf '%s  %s\n' "$INSTALLER_SHA256" "$TMP_INSTALLER" |
  /usr/bin/sha256sum --check --strict -
printf '%s  %s\n' "$EXPECTED_BUNDLE_SHA256" "$TMP_BUNDLE" |
  /usr/bin/sha256sum --check --strict -

/usr/bin/mv -n "$TMP_BUNDLE" "$PRIVATE_BUNDLE"
/usr/bin/mv -n "$TMP_INSTALLER" "$PRIVATE_INSTALLER"
test -f "$PRIVATE_BUNDLE"
test -f "$PRIVATE_INSTALLER"

# Prove the private bundle copy still equals the pinned opened bytes.
cmp -s "$BUNDLE_FD_PATH" "$PRIVATE_BUNDLE"

printf 'BOOTSTRAP_BUNDLE=%s\n' "$PRIVATE_BUNDLE"
printf 'BOOTSTRAP_INSTALLER=%s\n' "$PRIVATE_INSTALLER"
CLIENTFLOW_BOOTSTRAP

BOOTSTRAP_BUNDLE="$BOOTSTRAP_DIR/clientflow-approved.tar"
BOOTSTRAP_INSTALLER="$BOOTSTRAP_DIR/clientflow-installer-1.3.0.pyz"
```

If any check fails, remove the private bootstrap directory and do not run installer code:

```bash
sudo /usr/bin/rm -rf -- "$BOOTSTRAP_DIR"
```

The two root-owned files in `$BOOTSTRAP_DIR` are now the only accepted fresh-install inputs. The original download/build paths are no longer referenced.

Verify the private handoff once more through the installer parser:

```bash
sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" verify \
  --bundle "$BOOTSTRAP_BUNDLE" \
  --expected-bundle-sha256 "$APPROVED_BUNDLE_SHA256"
```

## 5. Fresh installation

Installation is for a clean Ubuntu Desktop 26.04 `amd64` client with an existing unprivileged kiosk user and a valid one-time enrollment code:

```bash
sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" install \
  --bundle "$BOOTSTRAP_BUNDLE" \
  --expected-bundle-sha256 "$APPROVED_BUNDLE_SHA256" \
  --backend-url https://<backend-origin> \
  --enrollment-code <one-time-code> \
  --kiosk-user <kiosk-user>
```

The fresh installer provisions the canonical domain/update credentials, immutable release files and rendered systemd definitions. It stops at `pending_manual_activation`.

## 6. Manual activation

Activation is explicit:

```bash
sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" activate \
  --release-id clientflow-1.3.0-seq-1201 \
  --expected-release-approval-reference <RELEASE_APPROVAL_REFERENCE>
```

Staging has already persisted the approved bundle SHA-256/size, candidate SHA-256, source commit and immutable release-approval reference. Activation first requires the operator-provided expected release-approval reference to match that staged provenance; it is not a new free-form approval. It then switches `/opt/clientflow/active`, applies managed definitions and runs health checks. Failure triggers the transaction's rollback behavior.

## 7. Validation before deployment

At minimum:

```bash
python -m compileall -q backend/service1 backend/migrations client/runtime client/release/lib scripts
python -m pytest -q backend/tests/test_*source*.py
```

A release/install change is not accepted as physically validated until the relevant Ubuntu installation/update and frozen-domain regressions have been run.
