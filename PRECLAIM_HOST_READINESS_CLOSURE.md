# Production Readiness — preclaim host readiness closure

Branch: `fix/preclaim-host-readiness-bootstrap`

Source identity is intentionally retained at ClientFlow `1.3.18`, release sequence `1219` while the candidate remains unapproved. Catalog authority remains `1.3.17/1218`.

## Finding

Category C/B — a clean Ubuntu 26.04 install could enter the consuming fresh-install flow without a canonical proof that `apt-get` and `curl` were operational. `curl` was not required by the installer, and no apt-less recovery authority existed if `/usr/bin/apt-get` was missing.

Trigger: missing/broken `/usr/bin/apt-get` or `/usr/bin/curl` on the clean host.

Consequence: production fresh install depended on manual host preparation or failed after the operator had already entered one-time authorities. That violates the clean-install and fail-closed preclaim contract.

Root cause: host package readiness lived only in later runtime platform preparation. The approved whole bundle contained no dedicated APT recovery artifact and `install_fresh()` had no preclaim host gate.

## Change

- The release platform lock now declares one `apt_3.2.0_amd64.deb` recovery artifact with exact size/SHA-256 and Ubuntu signed-repository provenance metadata.
- `host_bootstrap.ensure_preclaim_host_readiness()` runs only on the real `/` host and before fresh-install authorities are read or ClientFlow state is created.
- A working Ubuntu 26.04 amd64 `dpkg`/`dpkg-deb` is the non-APT bootstrap primitive.
- If `apt-get` is absent/broken, the installer reopens and deep-verifies the exact approved fresh-install bundle, requires the same approved whole-bundle SHA-256, extracts only the locked APT recovery artifact from the pinned payload region, verifies package metadata/hash/size, and reinstalls it using `dpkg`.
- Automatic APT downgrade is refused if the host records a newer installed apt version than the bundle recovery artifact.
- If `curl` is absent/broken after APT readiness, the installer establishes it with canonical Ubuntu APT (`apt-get update` + noninteractive `install --reinstall curl`).
- Any failure stops before enrollment authorities are read and before claim/local ClientFlow state mutation.

## Executable Ubuntu 26.04 gate

The Ubuntu 26.04 CI job now downloads the exact locked apt version through the runner's signed Ubuntu APT configuration, verifies that those bytes match the repo lock, temporarily removes `/usr/bin/apt-get`, restores it through the same direct `dpkg` recovery function, then temporarily removes `/usr/bin/curl` and restores it through the APT-backed curl path. The host is ephemeral and backups are retained for fail-safe restoration.

## Frozen risk

No Livestream, Terminal or Remote Desktop file is changed. No runtime agent or frozen systemd unit is changed. The new code executes only in the fresh-install host bootstrap plane before claim.

## Still open

Network/factory cleanup, pre-first-activation repair authority, GTK4 legacy GUI parity, periodic time integrity, quick settings, cfadmin popup parity, recovery/support UX, local power-event reporting, full capability-based legacy parity gate and obsolete frontend-contract cleanup remain open.

## CI authority-probe correction r2

The Ubuntu 26.04 host probe no longer asks the runner's mutable APT package index to resolve the locked historical `apt=3.2.0` version. That resolver can legitimately stop advertising an older exact version while the Ubuntu archive pool retains the immutable package file. The probe now fetches the exact baseline `apt_3.2.0_amd64.deb` from the locked `https://archive.ubuntu.com/ubuntu/pool/main/a/apt/` URL using Python's standard HTTPS stack, then requires exact locked size/SHA-256 and Debian package metadata before exercising the destructive apt/curl recovery path. Production recovery itself remains offline-from-network and consumes only the exact bytes embedded in the approved whole bundle.
