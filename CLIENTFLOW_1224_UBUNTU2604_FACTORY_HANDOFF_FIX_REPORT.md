# ClientFlow 1224 physical-failure closure — Ubuntu 26.04 factory handoff

Date: 2026-09-20

Suggested branch: `fix/clientflow-ubuntu2604-factory-handoff`

## Scope

This patch closes defects proven during physical fresh-install acceptance of the already-promoted ClientFlow 1.3.23 / release sequence 1224 on a clean Ubuntu 26.04.1 LTS client.

The failed 1.3.23/1224 release remains a physical acceptance **FAIL**. This source patch does not change `client/VERSION`, `client/release/release-input.json`, the release catalog, approval authority, or immutable release artifacts. After merge and green canonical CI, the normal release procedure must allocate a new source/build identity before physical acceptance restarts from phase 0.

## Proven findings

### CF-1224-SUDO-RS-01 — proven blocker

Physical host:
- Ubuntu 26.04.1 LTS
- sudo provider: `sudo-rs 0.2.13-0ubuntu1.2`
- visudo provider: `visudo-rs 0.2.13`

The temporary kiosk activation capability used classic sudoers command-digest syntax (`sha256:<digest>`). The physical host rejected it with `digest specifications are not supported`, so phase 01 stopped fail-closed before factory handoff.

The host physically parsed the replacement rule successfully:

`clientflow-kiosk ALL=(root) NOPASSWD: /usr/local/lib/clientflow-bootstrap/clientflow-fresh-install ""`

The patch removes only the unsupported digest specification. It retains:
- exact absolute root-owned helper path;
- no-arguments-only `""` command match;
- `NOPASSWD` limited to `clientflow-kiosk` and that exact command;
- root ownership / non-group-or-other-writable validation for both the helper and its parent directory;
- actual host `visudo -cf` validation;
- immediate removal of an invalid rule;
- removal of the temporary capability after durable pending installation.

### CF-1224-NETPLAN-CLEANUP-02 — proven blocker

Physical Ubuntu 26.04 NetworkManager/Netplan integration persisted the factory Wi-Fi in both installer Netplan state and NetworkManager-owned Netplan state. Deleting the current NetworkManager connection alone did not remove the original installer definition in `/etc/netplan/00-installer-config.yaml`.

An isolated physical test copied the live Netplan hierarchy to a private offline root, removed all `90-NM-*` YAML, then ran `netplan generate --root-dir`. The factory SSID and original UUID regenerated a NetworkManager profile from `00-installer-config.yaml`. This proved that the previous `nmcli connection delete` + `nmcli connection show` gate could not guarantee the shipping contract "no saved factory network profiles after reboot".

The patch now:
1. deletes current shipping NetworkManager connection profiles as before;
2. clears persistent Netplan connection subtrees with Netplan's own CLI:
   - `network.ethernets`
   - `network.wifis`
   - `network.modems`
   - `network.tunnels`
   - `network.nm-devices`
3. runs `netplan generate` fail-closed;
4. rejects handoff if generated NetworkManager profiles of the shipping network types can still be regenerated;
5. re-runs the persistent cleanup validation immediately before marking factory state `handoff_ready=true`.

Physical fix validation on Ubuntu 26.04 used an offline root and the exact planned `netplan set ...=null` operations. The merged result was only the generic NetworkManager renderer, no persistent NetworkManager profiles were generated, the factory SSID could not be regenerated, and live `/etc/netplan` remained byte-identical before/after the test.

### CF-1224-SYSTEMD-INHIBITOR-HARDENING-03 — compatibility hardening

Ubuntu 26.04.1 uses systemd 259. Its documented CLI exposes `--check-inhibitors=MODE` and `-i` (`--check-inhibitors=no`), while the older `--ignore-inhibitors` spelling is no longer advertised in `systemctl --help`.

The patch updates all active ClientFlow reboot authorities and their contracts to `--check-inhibitors=no` while retaining existing timeout / no-`--force` safety properties.

This item was not classified as a separate proven physical blocker because systemd 259 still accepted the old spelling during a safe `--dry-run` parser test. It is included as evidence-based compatibility hardening.

## Regression coverage

New focused source/runtime tests cover:
- sudo-rs-compatible exact/no-args temporary sudo capability;
- parent/helper ownership and permissions checks;
- persistent Netplan subtree cleanup;
- fail-closed regeneration detection;
- persistent validation before `handoff_ready=true`;
- systemd 259 inhibitor spelling across bootstrap, preactivation, system broker, and calendar broker.

Existing reboot, factory-flow, HTTP integration, system authority, and calendar tests were updated only where they asserted the superseded inhibitor spelling or inline network-type constant. Product behavior expectations were not weakened.

## Release discipline

- `client/VERSION`: unchanged (`1.3.23`)
- source `release_sequence`: unchanged (`1224`)
- catalog: unchanged
- immutable 1.3.23/1224 release bytes: unchanged
- failed 1.3.23/1224 physical acceptance: remains FAIL
- next step after merge + canonical green CI: allocate a new release identity through the normal release procedure, produce a new canonical USB, and restart clean physical acceptance from phase 0.

## Local validation results

- complete `scripts/tests`: 257 passed;
- affected backend contract/integration suite: 18 passed, 1 skipped;
- dependency contract: PASS;
- Python compileall: PASS;
- deterministic USB build: two byte-identical ZIPs, size 208620 bytes, SHA-256 `cff2ea07c8fc902ca3a00720c61fec56d732154d91678d19fc42911f4b55787e`;
- `USB_SHA256SUMS.txt` and `PAYLOAD_SHA256SUMS.txt`: PASS inside the candidate USB;
- Ruff and display-baseline validation remain canonical GitHub CI gates because the local tool container does not provide Ruff or `sqlmodel`.
