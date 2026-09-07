# ClientFlow legacy 1.1.19 local UX closure

Status: source closure for L119-03 and L119-12. Physical acceptance remains deferred until the next approved Ubuntu 26.04 clean-install verification.

## Findings closed

### L119-03 – local GTK GUI functional/layout parity

**Error / inconsistency**

The V2 GTK4 GUI existed, but it was a generic two-column status grid and did not preserve the physically proven legacy technician workflow.

**Trigger**

A technician opens the local ClientFlow GUI.

**Consequence**

Legacy grouping, name/locality context, separate network IP/MAC fields and copy affordances were missing.

**Evidence / root cause**

Legacy 1.1.19 groups the panel as `Handlinger`, `Systeminfo`, `Kioskinfo`, `Netværksinfo` and `Kalender – næste 7 dage`. It exposes separate active/WiFi/LAN IP/MAC rows and clipboard feedback. Current V2 source before this closure did not.

**Root cause**

The V2 rewrite treated the GUI as a generic readiness/status surface instead of a functional acceptance surface.

**Affected files**

- `client/libexec/local-gui`
- `client/release/lib/clientflow_release/cli.py`
- `scripts/tests/test_clientflow_local_ux_legacy119.py`

**Closure**

V2 remains GTK4 and keeps canonical V2 runtime authorities. The local GUI now preserves the legacy section structure, real seven-day calendar columns, client name/locality, separate active/WiFi/LAN IP+MAC rows and explicit copy buttons with `Kopieret!` feedback. Start/Stop kiosk continues through the existing narrow Display runtime RPC. Livestream, Remote Desktop and Terminal are displayed read-only.

Fresh install writes `/var/lib/clientflow/client-public.json` with only non-secret technician-facing metadata (`client_id`, name, locality, kiosk user). Credentials, keys, enrollment receipts, bundle hashes and resume material remain excluded.

### L119-12 – bounded local recovery/support UX

**Error / inconsistency**

V2 had no local equivalent to the legacy recovery/status/support/switch-user workflow.

**Trigger**

A technician needs local status, a support bundle or a transition from kiosk to `cfadmin` without backend control.

**Consequence**

Local diagnosis and maintenance required ad-hoc commands and risked broad service mutation.

**Evidence / root cause**

Legacy 1.1.19 contains `clientflow-recovery` and `clientflow-switch-user-admin`; V2 did not.

**Affected files**

- `client/libexec/clientflow-recovery`
- `client/libexec/clientflow-switch-user-admin`
- `client/libexec/local-gui`
- `scripts/tests/test_clientflow_local_ux_legacy119.py`

**Closure**

`clientflow-switch-user-admin` validates that the caller is exactly `clientflow-kiosk`, resolves the active `seat0` session, verifies local/non-remote/user/active ownership, and performs only `loginctl lock-session`. It does not restart services, change credentials or open a privileged shell.

`clientflow-recovery` exposes only:

- `status` – read-only system/session/network/time/ClientFlow unit summary;
- `bundle` – creates a bounded support archive on `~/Skrivebord`, falling back to `~/Desktop` (or an explicit test/output directory);
- `restart` – root-only and bounded to `systemctl restart clientflow.target`.

The support bundle deliberately excludes `/etc/clientflow`, credentials, private/update keys, environment dumps, command payloads and frozen-domain journals.

## Frozen-domain risk

Livestream, Terminal and Remote Desktop source/protocol/credentials/agents are unchanged. The GUI only reads their unit active state. Recovery restart addresses the aggregate `clientflow.target` only and contains no direct frozen-unit mutation path. A later physical regression must still verify that the local UX does not disturb the three frozen domains.

## Regression gate

The new tests prove:

- public client metadata is mode `0644` and contains only the non-secret allowlist;
- GUI source compiles and contains the accepted legacy sections/fields/copy affordances;
- Start/Stop remains the existing Display RPC;
- frozen domains remain read-only in the GUI;
- switch-user helper is syntactically valid and bounded to locking the exact active kiosk session;
- recovery `status` and `bundle` execute on the CI host;
- support archive contents exclude credential/private material;
- recovery mutation is limited to `clientflow.target`.

## Still open after this closure

- L119-08 full capability/executable legacy parity gate;
- L119-09 periodic Europe/Copenhagen + NTP integrity;
- L119-10 kiosk quick-settings parity;
- L119-11 popup baseline parity for both human accounts;
- L119-13 local reboot/shutdown attribution review;
- L119-14 obsolete/contradictory frontend/backend contracts.
