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

`client/VERSION` is the only manually maintained product-version value. The runtime wheel derives its PEP 621 version dynamically from that same authority, while `release_sequence` remains the separate monotonic anti-rollback identity component. Together they produce `clientflow-<version>-seq-<release_sequence>`. Active release commands in this procedure must derive or receive that exact identity; they must not copy a previous release's version, sequence or installer filename.

Source/build identity and runtime selection are intentionally separate release gates. During a release transition the source identity may move ahead **before** the runtime catalog does. The catalog must continue selecting the last physically published approved release until the new approved bundle has been materialized in the immutable 51M store. The `1.3.1/1202` transition from `1.3.0/1201` is a historical example of this staged promotion state, not an active selector instruction.

## 2. Build one canonical reproducible release candidate

Release candidates are produced by `.github/workflows/release-build.yml`, not on a ClientFlow kiosk and not from an arbitrary developer worktree. The manual workflow is a **build-only** authority: it can produce an unapproved candidate but cannot approve or publish a release.

The dispatch requires:

- `expected_source_sha`: the exact 40-character commit SHA. It must equal the workflow-dispatch SHA.
- `runtime_inputs_url`: a public HTTPS transport URL for a plain TAR containing the platform runtime inputs. The URL is transport only and is not an authority.
- `runtime_inputs_sha256`: the exact SHA-256 of that transport TAR.

The platform artifacts inside the transport TAR must match `client/release/runtime-platform-inputs.lock.json` byte-for-byte. That repo lock contains only source-independent platform bytes (`python-runtime-amd64.tar` plus third-party wheels); `clientflow_runtime-*.whl` is forbidden and is always rebuilt from the exact source commit.

The transport TAR itself is produced with the repository's canonical deterministic transport builder rather than an ad-hoc `tar` invocation:

```bash
python scripts/build_clientflow_runtime_input_transport.py \
  --input-dir /path/to/verified/platform-inputs \
  --output /path/to/clientflow-runtime-inputs-python-3.13.14-amd64.tar
```

The input directory must contain exactly `python-runtime-amd64.tar` and the locked third-party wheels under `wheelhouse/`. The builder opens each source artifact with no-follow semantics, verifies size/SHA-256 against the repo lock, writes a deterministic USTAR archive with normalized ownership/mode/mtime metadata, re-verifies every member in the completed TAR, and uses no-replace publication for the output path. Two builds from the same locked bytes must therefore produce the same transport SHA-256. The resulting TAR may be hosted on any ordinary public HTTPS asset service (for example a repository release asset); the hosting location is transport only because the workflow independently requires both the exact outer TAR SHA-256 and every repo-locked inner artifact hash/size.

Before building, the workflow:

1. checks out exactly `expected_source_sha` with persisted Git credentials disabled;
2. requires the dispatched workflow SHA and checkout HEAD to equal that SHA and the worktree to be clean;
3. queries GitHub Actions read-only and requires a successful canonical `CI` **push** run for the same SHA and branch;
4. fetches the runtime-input transport over HTTPS, verifies its outer SHA-256, and materializes only the exact regular files declared by the repo lock;
5. pins Python `3.13.14`, pip `26.1.2` and setuptools `83.0.0`; setuptools is installed from `client/release/release-build-requirements.lock.txt` with `--require-hashes --only-binary=:all:`.

Two independent GitHub-hosted runners then build the same commit with the commit timestamp as `SOURCE_DATE_EPOCH`. A third job downloads both outputs and requires byte-identical candidate bundle, embedded/loose installer, payload, candidate manifest and checksum file. It also verifies manifest source provenance and writes `REPRODUCIBILITY.json`. Only after this comparison is one **unapproved reproducible handoff** uploaded as a workflow artifact. GitHub build provenance attestation is supplemental evidence; it does not replace ClientFlow approval.

The canonical handoff artifact is named:

```text
clientflow-reproducible-unapproved-<FULL_SOURCE_SHA>
```

Download that artifact from the successful release-build workflow. Its candidate remains `deployable: false`. Record the exact candidate and embedded fresh-installer SHA-256 values from `REPRODUCIBILITY.json` / `SHA256SUMS`; those exact values are inputs to the separate approval gate.

For local development only, `scripts/build_clientflow_release.py` remains available, but it fails unless the exact release-build toolchain is installed and its output is **not** a canonical release handoff unless it has passed the two-runner workflow gate above.

## 3. Approve one exact candidate

Approval uses no release signing key. It is an explicit gate bound to the exact reproducible candidate hash, exact source commit and an approval reference. Use the exact candidate pathname from the reproducible handoff; do not reconstruct its release identity from an older example:

```bash
CANDIDATE_BUNDLE="/path/to/exact-reproducible-candidate.tar"
APPROVED_BUNDLE="/path/to/approved-output.tar"

python scripts/approve_clientflow_release.py \
  "$CANDIDATE_BUNDLE" \
  --output "$APPROVED_BUNDLE" \
  --expected-candidate-sha256 <EXACT_CANDIDATE_SHA256> \
  --expected-installer-sha256 <EXACT_INSTALLER_SHA256> \
  --expected-source-commit <FULL_40_CHARACTER_GIT_SHA> \
  --approval-reference <CHANGE_OR_RELEASE_REFERENCE> \
  --approve-release
```

Only the approved output may have `deployable: true`. The approval gate opens the candidate once with no-follow semantics and keeps that exact file identity pinned while whole-bundle SHA-256, manifest/payload, the embedded fresh-installer member, runtime preflight and promotion are evaluated. Replacing the candidate pathname during approval cannot change the bytes being approved. Schema 8 requires the fresh installer to be physically embedded in the same bundle and to match the exact `fresh_installer` descriptor.

Record the SHA-256 of the approved bundle. That hash is the external trust anchor for the physical handoff.

## 4. Publish approved bytes before runtime-catalog promotion

Publication is deliberately bound to the exact source/build identity from `client/VERSION` and `client/release/release-input.json`, **not** to the runtime selection catalog. This removes the circular dependency where a release had to become selectable before its approved bytes could exist in the backend artifact store.

From the running backend service context where `/var/data/clientflow-release-artifacts/store` is mounted, publish the exact approved bundle:

```bash
APPROVED_BUNDLE="/path/to/exact-approved-bundle.tar"

python scripts/publish_clientflow_release.py \
  "$APPROVED_BUNDLE" \
  --artifact-dir /var/data/clientflow-release-artifacts/store \
  --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256> \
  --expected-approval-reference <CHANGE_OR_RELEASE_REFERENCE> \
  --expected-source-commit <FULL_40_CHARACTER_GIT_SHA> \
  --publish-release
```

The publication gate verifies the approved bundle against the current source checkout's exact source/build identity, the supplied whole-bundle SHA-256, approval reference and source commit, then atomically no-replace publishes `<release-id>.tar`. The old catalog remains active throughout this step.

Only after the immutable store has been independently re-read and verified to contain those exact approved bytes may a **separate catalog-promotion change** move `catalog_sequence`, `latest_stable`, `default_install_version` and the single selectable release to that exact published release. That promotion is the point at which fresh-install authorizations may begin selecting the new release.

The approved `1.3.0/1201` source predates the privileged update-controller: its updater host stops at verified/staged state and its installed updater unit has no controller handoff. Therefore the `1.3.1/1202` catalog entry must **not** claim in-place compatibility from `1.3.0`; its minimum current version must be `1.3.1`. The first canonical in-place update proof is from a fresh-installed `1.3.1` client to a later release whose policy explicitly accepts `1.3.1`.

Do not merge catalog promotion before publication. A selected release with no matching immutable artifact, or a compatibility range that claims an unavailable bootstrap path, is a release-chain failure.

### Canonical customer fresh-install path (legacy 1.1.19 operator flow, V2 trust boundary)

The normal preparation media exposes the repo-owned two-phase operator flow rather than a release selector. USB preflight verifies its own repo-owned bootstrap payload and creates **01 Klient klargøring**. Phase 1 is the trusted office/factory boundary: it establishes connectivity, confirms the client name, creates the canonical `clientflow-kiosk` and `cfadmin` accounts, reads the `cfadmin` password directly from the controlling TTY without persisting it, configures GDM autologin to kiosk, creates **02 Aktiver ClientFlow** on the kiosk desktop, and grants kiosk only a temporary `sudo -n` capability for the SHA-256-bound root-owned customer activation helper with no arguments. Before the confirmed reboot, all saved WiFi/Ethernet/GSM/CDMA/VPN/WireGuard NetworkManager profiles are removed and the complete shipping handoff is validated fail-closed. Release selection, enrollment authority, client secrets and runtime activation still do not happen in phase 1.

The resulting post-`01` state is the customer shipping state: the temporary Ubuntu installer identity is no longer the graphical login, office network profiles are gone, and the customer neither knows nor enters a Linux administrator password. The canonical fresh installer accepts the two preprovisioned human accounts only when `/var/lib/clientflow-bootstrap/factory-state.json` is root-owned/private, schema 2, `handoff_ready=true`, matches the explicit client name and canonical account names, and the account contract is revalidated. Other existing ClientFlow traces still fail closed.

At the customer, the operator opens **02 Aktiver ClientFlow** once. The visible order is customer network, client identity/locality, then the formatted `CF-____-____-____` code. The helper exchanges that code with `/api/enrollment/fresh-install-bootstrap`, receives the token's durable creation-time exact-release binding plus signed authorization internally, downloads only `/api/enrollment/fresh-install-artifact`, verifies exact approved whole-bundle SHA-256/size and the embedded installer, and passes the code + authorization directly to the consuming installer over stdin. There is no `latest`/`stable` release authority on the USB media and the authorization is never displayed or persisted.

A definite pre-commit first-claim HTTP 4xx is surfaced by the canonical installer as an explicit `first_claim_rejected` result after its minimal local preclaim state has been removed; the customer wrapper then keeps name/locality and asks only for a new CF-code. Ambiguous transport/5xx outcomes remain resumable because the backend may already have committed the receipt. For that case the already verified exact approved bundle is retained root-only as `/var/lib/clientflow-bootstrap/pending-approved-bundle.tar`; reopening **02 Aktiver ClientFlow** resumes the same install ID/release binding without asking for a consumed one-time code. The cached artifact is removed as soon as durable `pending_manual_activation` has been reached.

After durable `pending_manual_activation`, the helper first removes the temporary customer-activation sudoers capability, first-login trust helper and installation desktop icon, then materializes the minimum GDM/AccountsService kiosk-login baseline from the immutable staged runtime, installs a temporary `clientflow-preactivation-gui.service`, enables the narrow `clientflow-first-activation.service` waiter and offers the second legacy-style confirmed reboot. The client is still backend-pending and no ClientFlow runtime domain is activated. After reboot the temporary service execs the exact staged release's existing local GUI as `clientflow-kiosk` in explicit status-only mode: it shows the legacy layout with `Registreret – afventer godkendelse`, has Start/Stop kiosk disabled, exposes no administrator-switch action and starts none of Display/Calendar/Terminal/Remote Desktop/Livestream. Approved first activation instead publishes a root-owned exact-release handoff under `/run/clientflow`; the already visible GUI validates that handoff plus the canonical active symlink/runtime socket, switches to active paths in-place, and the Display runtime adopts its existing PID. The GTK window is therefore not closed/restarted during approval, while rollback removes the handoff and returns the same process to fail-closed pending mode. The superadmin approval payload may carry the client’s kiosk URL; when supplied, backend stores it as canonical Display desired-state in the same approval transaction so the first active Display-agent reconciliation can queue `apply_configuration` without a separate post-approval client edit. After a superadmin approves that exact client, the waiter requires the canonical local `clientflow-kiosk` seat0 Wayland session and repeatedly invokes only the immutable staged `runtime/bin/python -P -m clientflow_release activate` command with the original release-id and approval-reference. The staged canonical activation CLI re-proves backend client approval before runtime mutation. **The operator does not open Aktiver ClientFlow a second time after approval.** Stable updater remains reserved for normal post-activation polling and the explicit pre-first-activation repair path.

The detailed shell blocks in sections 5-7 remain an engineering/release-verification description of the same trust boundary; they are **not** the normal customer/operator handoff. Historical enrollment rows without a durable 55A release binding must fail closed and be revoked/recreated; they must never be rebound to the current catalog.

## 5. Materialize a pinned fresh-install bootstrap before executing installer code

The approved bundle SHA-256 is the external trust anchor. The fresh installer is **not** a second loose trust artifact: schema 8 embeds its exact bytes inside the approved bundle.

The physical handoff must therefore keep one concrete bundle file identity open while it hashes that file, reads `manifest.json`, and extracts the embedded installer. The extracted installer and an exact copy of the approved bundle are materialized into a new root-owned private directory under `/run`; installer code is first executed from that private copy, never from a user-writable build/download pathname.

Run the following as one uninterrupted Bash block in the **same shell** that successfully ran `clientflow_fresh_install_download`. The block reuses the already-exported `BUNDLE` and `APPROVED_BUNDLE_SHA256`; do not retype either value. A bootstrap validation failure returns from the helper instead of exiting the interactive shell, so the transient enrollment authorities remain available for an exact retry/diagnosis. No ClientFlow installer code runs inside the bootstrap block; it uses only host `bash`, `sha256sum`, `tar`, `python3`, `stat`, `cmp`, and filesystem primitives:

```bash
clientflow_materialize_fresh_bootstrap() {
  # These values were already pinned by clientflow_fresh_install_download in
  # this same shell. Do not retype or replace either trust value here.
  test -n "${BUNDLE:-}" || { echo "BUNDLE mangler fra fresh-install handoff" >&2; return 1; }
  test -n "${APPROVED_BUNDLE_SHA256:-}" || {
    echo "APPROVED_BUNDLE_SHA256 mangler fra fresh-install handoff" >&2
    return 1
  }

  BOOTSTRAP_DIR="$(
    sudo /usr/bin/mktemp -d /run/clientflow-fresh-install.XXXXXXXX
  )" || return 1
  sudo /usr/bin/chown root:root "$BOOTSTRAP_DIR" || return 1
  sudo /usr/bin/chmod 0700 "$BOOTSTRAP_DIR" || return 1

  BOOTSTRAP_RESULT=()
  mapfile -t BOOTSTRAP_RESULT < <(
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
  /usr/bin/sha256sum --check --strict - >&2

read -r RELEASE_ID INSTALLER_FILE INSTALLER_SIZE INSTALLER_SHA256 < <(
  /usr/bin/tar -xOf "$BUNDLE_FD_PATH" manifest.json |
  /usr/bin/python3 -I -c \
    'import json,sys; m=json.load(sys.stdin); x=m["fresh_installer"]; print(m["release_id"], x["file"], x["size"], x["sha256"])'
)

test -n "$RELEASE_ID"
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
  /usr/bin/sha256sum --check --strict - >&2
printf '%s  %s\n' "$EXPECTED_BUNDLE_SHA256" "$TMP_BUNDLE" |
  /usr/bin/sha256sum --check --strict - >&2

/usr/bin/mv -n "$TMP_BUNDLE" "$PRIVATE_BUNDLE"
/usr/bin/mv -n "$TMP_INSTALLER" "$PRIVATE_INSTALLER"
test -f "$PRIVATE_BUNDLE"
test -f "$PRIVATE_INSTALLER"

# Prove the private bundle copy still equals the pinned opened bytes.
cmp -s "$BUNDLE_FD_PATH" "$PRIVATE_BUNDLE"

# Stdout is deliberately reserved for these three machine-readable values;
# integrity-check output above is sent to stderr and remains visible.
printf '%s\n' "$RELEASE_ID"
printf '%s\n' "$PRIVATE_BUNDLE"
printf '%s\n' "$PRIVATE_INSTALLER"
CLIENTFLOW_BOOTSTRAP
  )

  test "${#BOOTSTRAP_RESULT[@]}" -eq 3 || return 1
  BOOTSTRAP_RELEASE_ID="${BOOTSTRAP_RESULT[0]}"
  BOOTSTRAP_BUNDLE="${BOOTSTRAP_RESULT[1]}"
  BOOTSTRAP_INSTALLER="${BOOTSTRAP_RESULT[2]}"

  test "$BOOTSTRAP_BUNDLE" = "$BOOTSTRAP_DIR/clientflow-approved.tar" || return 1
  case "$BOOTSTRAP_INSTALLER" in
    "$BOOTSTRAP_DIR"/clientflow-installer-*.pyz) ;;
    *) echo "Ugyldig materialiseret installersti" >&2; return 1 ;;
  esac
}

if clientflow_materialize_fresh_bootstrap; then
  unset -f clientflow_materialize_fresh_bootstrap
  printf '%s\n' 'Fresh-install bootstrap materialized from the pinned handoff.'
else
  BOOTSTRAP_RC=$?
  unset -f clientflow_materialize_fresh_bootstrap
  printf '%s\n' 'STOP: fresh-install bootstrap failed; keep this shell open and clean the private bootstrap directory.' >&2
fi
```

If any check fails, remove the private bootstrap directory and do not run installer code:

```bash
sudo /usr/bin/rm -rf -- "$BOOTSTRAP_DIR"
```

The two root-owned files in `$BOOTSTRAP_DIR` are now the only accepted fresh-install inputs. The original download/build paths are no longer referenced. `BOOTSTRAP_RELEASE_ID` and `BOOTSTRAP_INSTALLER` came from the same pinned approved bundle manifest used for extraction; no release version or installer filename is hardcoded by the procedure.

Verify the private handoff once more through the installer parser:

```bash
sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" verify \
  --bundle "$BOOTSTRAP_BUNDLE" \
  --expected-bundle-sha256 "$APPROVED_BUNDLE_SHA256"
```

## 6. Fresh installation

Installation is for a clean Ubuntu Desktop 26.04 `amd64` client. The Ubuntu bootstrap user is only the temporary operator session; after committed claim the installer creates the fixed dedicated kiosk account `clientflow-kiosk` plus the fixed local administrator `cfadmin`. The **first** consuming claim requires the same one-time enrollment code and signed `FRESH_INSTALL_AUTHORIZATION` that authorized the exact approved bundle download. Both are transient capabilities and must not be written into ClientFlow install-state.

The generated admin handoff is non-secret: paste it first, then run `clientflow_fresh_install_download` and paste the separately copied enrollment code and signed authorization only at its hidden prompts. The function keeps `ENROLLMENT_CODE` and `FRESH_INSTALL_AUTHORIZATION` as transient values in the same shell for the later consuming claim, while neither capability appears in the pasted handoff command or shell history. Keep that same shell and require both before starting the first mutation:

```bash
test -n "${ENROLLMENT_CODE:-}"
test -n "${FRESH_INSTALL_AUTHORIZATION:-}"
test -n "${CLIENTFLOW_CLIENT_NAME:-}"

INSTALL_ARGS=(
  install
  --bundle "$BOOTSTRAP_BUNDLE"
  --expected-bundle-sha256 "$APPROVED_BUNDLE_SHA256"
  --backend-url https://<backend-origin>
  --fresh-install-authority-stdin
  --kiosk-user clientflow-kiosk
  --name "$CLIENTFLOW_CLIENT_NAME"
)
if test -n "${CLIENTFLOW_LOCALITY:-}"; then
  INSTALL_ARGS+=(--locality "$CLIENTFLOW_LOCALITY")
fi
if test -n "${CLIENTFLOW_BOOTSTRAP_NETWORK_UUID:-}"; then
  INSTALL_ARGS+=(--bootstrap-network-connection-uuid "$CLIENTFLOW_BOOTSTRAP_NETWORK_UUID")
fi

printf '%s\n%s\n' "$ENROLLMENT_CODE" "$FRESH_INSTALL_AUTHORIZATION" |
  sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" "${INSTALL_ARGS[@]}"

unset ENROLLMENT_CODE FRESH_INSTALL_AUTHORIZATION
```



Before the block above, set `CLIENTFLOW_CLIENT_NAME` explicitly to the physical client's intended backend name. `CLIENTFLOW_LOCALITY` is optional. The installer no longer allows a brand-new consuming claim to silently fall back to hostname/"Ny infoskærm"; the explicit name and locality are persisted as non-secret lifecycle metadata and must remain identical on crash/resume.

Fresh install also performs a read-only NetworkManager/backend preflight **before** it reads the enrollment code or signed authorization from stdin. Ubuntu Desktop must have a running NetworkManager with at least one connected non-loopback device, and the configured backend `/health` endpoint must return canonical `{"status":"ok"}` over the same TLS trust path.

If the current connection is a temporary factory/test WiFi or Ethernet profile that ClientFlow should remove after healthy first activation, obtain its active NetworkManager UUID and set `CLIENTFLOW_BOOTSTRAP_NETWORK_UUID` before running the block. This is an explicit ownership marker. ClientFlow never enumerates-and-deletes arbitrary saved profiles: only the exact active UUID/type/name recorded before claim may later be deleted. Leave the variable unset for permanent customer/site connectivity.

The one-time enrollment code and signed fresh-install authorization are passed only over stdin; they are never present in the privileged installer argv recorded by `sudo`/journald. The variables are unset immediately after a successful claim/install return.


After the backend claim has committed, the installer restores the physically proven legacy human-account contract before materializing the runtime definitions: `clientflow-kiosk` is created as the dedicated non-admin autologin account, while `cfadmin` is created as the local sudo administrator. The installer prompts twice for the `cfadmin` password through the controlling TTY; the cleartext password is never included in argv or persisted in ClientFlow state. This account mutation remains post-claim so a definitive claim mismatch cannot leave local human-account state behind.

The installer derives a non-secret release binding from the locally verified approved bundle: release ID/version/sequence, whole-bundle SHA-256/size, immutable approval reference, candidate provenance and source commit. Backend claim verifies that complete binding against the signed authorization for the same enrollment-token **before** creating client/credential state or consuming the code. The existing enrollment receipt then commits its resume-proof hash to that exact binding, so crash recovery cannot switch release provenance without introducing a parallel release-authority table.

Before the first claim request, the installer may persist only the minimum crash-resume material required to survive an ambiguous consuming transaction: install ID/seed, optional pinned CA, and the system/update private keys whose public material is committed by the receipt. Release staging, managed systemd definitions, sysusers and tmpfiles are deferred until the claim succeeds. A definitive HTTP 4xx rejection of the first claim removes that pre-claim material and restores the original clean ClientFlow filesystem state; transport failures, invalid/ambiguous responses and HTTP 5xx retain the minimum material because the backend may already have committed the receipt.

If the install command is interrupted after local install-state exists, rerun against the **same** bundle, backend and kiosk user. If the original one-time code/authorization are no longer available, those two options may be omitted only for recovery: the backend will resume without them **only if** the first claim had already committed a receipt whose resume-proof commitment matches the same install ID and exact release binding, while the original system/update keys still match. If consumption never committed, the retry is rejected instead of silently authorizing a different release.

That `install` recovery applies only while the local release transaction is still pre-activation. Once an activation intent exists or an active release/symlink is present, rerunning fresh `install` is rejected **before** updater/systemd mutation; continue with the canonical activation/update recovery instead. This prevents a stale `pending_manual_activation` install-state from disabling or otherwise mutating the update plane of an already activated client.

The fresh installer provisions the canonical domain/update credentials, immutable release files and rendered systemd definitions. It also materializes the stable updater host, but `clientflow-updater.timer` is explicitly kept `disabled` and `inactive`. It stops at durable `pending_manual_activation`. In normal customer UX the outer **02 Aktiver ClientFlow** helper then runs the staged runtime's narrow `clientflow_runtime.display_session_prepare` module, which materializes only the minimum GDM/AccountsService login baseline, enables the first-activation approval waiter and offers one operator-confirmed reboot using `systemctl --no-block --check-inhibitors=no reboot` with a 10-second command timeout and no `--force`. This pre-activation preparation does not install/start Chrome, start ClientFlow runtime services, switch `/opt/clientflow/active`, enable `clientflow.target`, or weaken activation health. It does install the bootstrap-owned status-only local GUI service described above; that service validates the exact staged release, waits for the canonical kiosk Wayland socket, drops root to `clientflow-kiosk`, and execs the staged `client-runtime/libexec/local-gui` with `CLIENTFLOW_GUI_MODE=preactivation`. At this point the newly claimed client is still backend-pending, so its update credential is expected to remain backend-rejected and the client must not poll the update plane. A superadmin must approve that exact client through the existing canonical backend approval flow before local activation can succeed.

## 7. Backend approval and canonical first activation

Backend approval is explicit and manual; the subsequent local first-activation dispatch is automatic in the normal legacy-compatible customer flow. Before any local runtime mutation, first activation proves that the already-provisioned `status` credential is active by requesting its canonical backend token. Pending, rejected, malformed or unavailable approval proof fails closed before `/opt/clientflow/active`, managed systemd definitions or runtime services are changed. The stable updater timer also remains disabled during this proof. This is a client-lifecycle approval gate, not a new release authority.

After the exact client has been approved in the backend, `clientflow-first-activation.service` invokes the same canonical staged command automatically; no second operator click is required. For engineering verification, the equivalent canonical staged invocation is:

```bash
RELEASE_ROOT="/opt/clientflow/releases/$BOOTSTRAP_RELEASE_ID"
sudo env \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONNOUSERSITE=1 \
  PYTHONPATH="$RELEASE_ROOT/release/lib" \
  "$RELEASE_ROOT/runtime/bin/python" -P -m clientflow_release activate \
  --release-id "$BOOTSTRAP_RELEASE_ID" \
  --expected-release-approval-reference <RELEASE_APPROVAL_REFERENCE>
```

The pre-activation reboot has already made the canonical GDM/autologin login configuration authoritative and established the kiosk Wayland session required by Display readiness. Full Display platform preparation reasserts the complete kiosk host baseline during activation but does not restart `gdm3` inside the transaction. The baseline keeps Chrome in normal browser mode with `--start-fullscreen` (never `--kiosk`), disables idle lock/screensaver/suspend/dim, blocks Bluetooth, suppresses kiosk-user update/crash popups, hides and ACL-blocks local Settings/Terminal/package/network/Bluetooth administration apps for the kiosk user, installs a kiosk-user-only polkit deny rule for privileged system changes, preserves logout/user-switch for `cfadmin`, and enforces Europe/Copenhagen + NTP.

The local GTK4 GUI preserves the proven legacy technician workflow as a V2-native surface: `Handlinger`, `Systeminfo`, `Kioskinfo`, `Netværksinfo` and `Kalender – næste 7 dage`, including separate active/WiFi/LAN IP+MAC copy fields. Fresh install publishes only non-secret name/locality/client metadata in `/var/lib/clientflow/client-public.json`; enrollment credentials and keys remain private. Local support is bounded to `clientflow-recovery status|bundle|restart`, where restart addresses only `clientflow.target`. `clientflow-switch-user-admin` only locks the exact active `clientflow-kiosk` seat0 session so GDM can present `cfadmin`; it has no privileged shell or frozen-domain mutation path.

After activation health is green, the installer removes the temporary Ubuntu bootstrap user and, if and only if an exact NetworkManager profile was explicitly marked during preclaim, deletes that exact profile. The install-state is first durably marked `activated`; if profile cleanup fails or the UUID/type/name no longer matches, cleanup fails closed and the exact marker remains pending for a same-release activation retry. Unmarked customer/site profiles are never touched.

After activation health is green and any explicitly marked bootstrap-network cleanup has completed, perform one controlled reboot before the reboot/reconnect verification gate. The reboot is part of kiosk-session materialization, not release authority.

Release staging is serialized against activation recovery: while `activation_intent` is present, `stage_bundle()` rejects any new release before extraction or filesystem staging begins. This prevents the updater/controller from layering a second release transaction over a crash-resume of first activation or an in-place activation. Once the existing activation is durably completed or rolled back and the intent is cleared, the verified deployment can be retried normally.

Staging has already persisted the approved bundle SHA-256/size, candidate SHA-256, source commit and immutable release-approval reference. Activation first requires the operator-provided expected release-approval reference to match that staged provenance; it is not a new free-form approval. Fresh first-activation authorization is keyed from durable `active_release_id`, not from the active-symlink: if a crash leaves the target symlink in place while first activation is still uncommitted, every activation resume must re-prove the same client is backend-approved before further local mutation. It then switches `/opt/clientflow/active`, applies managed definitions and starts `clientflow.target` **without boot-enabling it** so runtime health can be evaluated fail-closed. A successful health boundary is persisted while the exact `activation_intent` is still durable; only after that durable proof may `clientflow.target` be enabled for reboot persistence. This ordering applies to first activation and in-place update activation/rollback, so abrupt power loss before health cannot make an unverified release auto-start on the next boot. Only after first-activation health is durably green is `clientflow-updater.timer` enabled and started. If first activation fails at any point, rollback returns to staged/pending with no active release, `clientflow.target` disabled and the updater timer disabled/inactive.

### Pre-first-activation repair

A failed first activation must not require wipe, re-enrollment, a new client identity or cloned state. When the client is already backend-approved but still has **no active release**, a superadmin may explicitly authorize a `pre_first_activation_repair` deployment to one exact, strictly newer approved catalog release. Backend derives the current baseline from the server-side `client_enrolled` claim audit written in the same claim transaction and rejects repair if a canonical Status runtime is online, the claim binding is unavailable/invalid, the target is not newer, or no repair reason is supplied. Normal deployments still require a fresh online canonical Status version.

The pending client keeps `clientflow-updater.timer` disabled. After the repair deployment has been authorized, run the persistent stable updater host explicitly:

```bash
sudo /usr/bin/python3 -I /usr/lib/clientflow/updater/clientflow-updater.pyz repair-first-activation
```

This operator command is intentionally stored in the stable updater plane rather than the transient `$BOOTSTRAP_INSTALLER` under `/run`, so a reboot after the failed activation cannot remove the repair capability. The command first proves the local state is still the exact original `pending_manual_activation` claim baseline with `active_release_id=None`, no active symlink and no activation intent. It then uses the existing update identity to fetch the backend-authorized exact whole bundle, verifies it through the normal updater boundary, stages it through the normal release transaction, obtains backend activation authorization, re-proves the existing backend client-approval gate, and health-activates the repair target.

Successful repaired first activation preserves the immutable original `fresh_install_binding` as historical claim authority, records the newer first active release separately, cleans up the recorded bootstrap user, and only then opens the normal updater timer. Any mismatch fails closed without wipe or re-enrollment.

## 8. Validation before deployment

At minimum:

```bash
python -m compileall -q backend/service1 backend/migrations client/runtime client/release/lib scripts
python -m pytest -q \
  backend/tests/test_clientflow_operational_compatibility_gate.py \
  backend/tests/test_clientflow_activation_intent.py \
  backend/tests/test_*source*.py \
  scripts/tests/test_clientflow_release_procedure_contract.py
```

A release/install change is not accepted as physically validated until the relevant Ubuntu installation/update and frozen-domain regressions have been run.
