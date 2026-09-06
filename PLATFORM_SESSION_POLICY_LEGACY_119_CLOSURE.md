# ClientFlow legacy 1.1.19 platform/session-policy closure

Status: source closure for L119-09, L119-10 and L119-11. Physical acceptance remains deferred until the next approved Ubuntu 26.04 clean-install verification.

## L119-09 – periodic Europe/Copenhagen + NTP integrity

**Error / inconsistency**

V2 corrected timezone/NTP only during `clientflow-platform-prepare`; later drift was not repaired.

**Trigger**

Timezone or NTP state changes after activation/reboot.

**Consequence**

The client can diverge from the canonical Europe/Copenhagen/NTP baseline until a later activation.

**Root cause**

No recurring time-integrity unit existed in the managed release payload.

**Affected files**

- `client/runtime/clientflow_runtime/time_integrity.py`
- `client/runtime/pyproject.toml`
- `client/release/lib/clientflow_release/runtime_prepare.py`
- `client/systemd/clientflow-time-integrity.service`
- `client/systemd/clientflow-time-integrity.timer`
- `client/systemd/clientflow.target`

**Closure**

The root-owned oneshot verifies/corrects `Europe/Copenhagen` and NTP through `/usr/bin/timedatectl`, then verifies the resulting state. The target owns a boot-delayed hourly timer; the service has no ClientFlow credential access and no frozen-domain authority.

## L119-10 – recurring kiosk quick-settings parity

**Error / inconsistency**

Legacy reasserted the physically proven kiosk quick-settings baseline; V2 only set part of it during Display preparation.

**Trigger**

The local kiosk user changes WiFi/power/audio/night-light/default colour scheme.

**Consequence**

The physical signage session can drift from the accepted baseline.

**Root cause**

V2 had no recurring session-policy authority scoped to the active kiosk session.

**Affected files**

- `client/runtime/clientflow_runtime/kiosk_session_policy.py`
- `client/runtime/pyproject.toml`
- `client/release/lib/clientflow_release/runtime_prepare.py`
- `client/systemd/clientflow-kiosk-session-policy.service`
- `client/systemd/clientflow-kiosk-session-policy.timer`
- `client/systemd/clientflow.target`

**Closure**

The policy first proves that `clientflow-kiosk` owns the active local `seat0` session. Only then it reasserts WiFi on, Bluetooth blocked, balanced power profile when available, audio unmuted/60% when the kiosk PipeWire control plane is ready, night-light off and default colour scheme. If `powerprofilesctl`, `wpctl`, session bus or PipeWire are not yet available, the condition is reported as bounded/optional and the recurring timer retries later. `cfadmin` is never targeted by the mutation path.

## L119-11 – popup baseline for both human accounts

**Error / inconsistency**

V2 wrote update/crash autostart suppression only to the kiosk account. Legacy acceptance applies the human-session popup baseline to both kiosk and maintenance account and includes a Firefox first-run/default-browser/update policy baseline.

**Trigger**

`clientflow-kiosk` or `cfadmin` starts a graphical session after package/browser events.

**Consequence**

Update/crash/default-browser/first-run UI can cover signage or maintenance workflow.

**Root cause**

`display_platform_prepare.py` treated popup suppression as kiosk-only instead of a two-human-account baseline.

**Affected files**

- `client/runtime/clientflow_runtime/display_platform_prepare.py`
- `scripts/tests/test_clientflow_platform_session_policy_legacy119.py`

**Closure**

The same bounded autostart suppression is materialized for both canonical human accounts. A root-owned `/etc/firefox/policies/policies.json` disables Firefox app-update prompts, studies/telemetry, default-browser checking and first/post-update pages. No ClientFlow credentials, private keys or frozen agents are read or changed.

## Frozen-domain risk

Livestream, Terminal and Remote Desktop source/protocol/credentials/agents are unchanged. The new policy units operate only on host time and the local graphical kiosk session. They neither import nor execute frozen-domain helpers.

## Regression gate

The new tests prove:

- time drift is corrected and verified;
- the time timer is target-owned, boot-delayed, recurring and persistent in the managed unit contract;
- kiosk quick-settings mutate only after an active local `clientflow-kiosk` seat0 session is proven;
- no active kiosk session produces no quick-settings mutation;
- WiFi/Bluetooth/power/audio/night-light/default scheme commands are explicitly bounded;
- popup autostart baseline is materialized for both `clientflow-kiosk` and `cfadmin`;
- Firefox popup/default/update policy is materialized without ClientFlow credential paths;
- new runtime console scripts are part of the exact release entrypoint inventory;
- the full ClientFlow systemd boot graph remains cycle-free.

## Still open after this closure

- L119-08 full capability/executable legacy parity gate;
- L119-13 local reboot/shutdown attribution review;
- L119-14 obsolete/contradictory frontend/backend contracts.
