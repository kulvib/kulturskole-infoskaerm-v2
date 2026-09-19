# ClientFlow V2 pre-activation local GUI closure

## Decision

A claimed customer client in durable `pending_manual_activation` must not present a blank appliance desktop while waiting for backend approval. After the customer reboot, the existing release-owned local GTK4 GUI is visible in the same legacy 1.1.19 layout, but only as a status surface.

## Lifecycle contract

- `01 Klient klargøring`: no ClientFlow GUI; only `02 Aktiver ClientFlow` is exposed to the customer handoff state.
- `02` completes exact-release claim/staging and reaches durable `pending_manual_activation`.
- Before the confirmed reboot, bootstrap installs and enables `clientflow-preactivation-gui.service` plus the existing first-activation waiter.
- After reboot, the GUI service waits for the canonical active `clientflow-kiosk` / `seat0` / local Wayland session and an owned `wayland-*` socket.
- The service validates the exact staged release and its `client-runtime/libexec/local-gui`, then drops root privileges with `initgroups`/`setgid`/`setuid` before execing `/usr/bin/python3` as `clientflow-kiosk`.
- The GUI receives `CLIENTFLOW_GUI_MODE=preactivation` and a staged `VERSION` path. It does not depend on `/opt/clientflow/active`.
- `clientflow.target` remains disabled/inactive. Terminal, Remote Desktop, Livestream, Display runtime, Calendar, Browser Guard and updater remain inactive.
- Start/Stop kiosk are disabled and the RPC path is guarded in code. No `Skift til administrator` action is exposed.
- Backend approval remains the sole gate for canonical first activation.
- The temporary GUI unit has `Before=clientflow.target` and `Conflicts=clientflow.target`. When approved activation starts the target, systemd stops the pending GUI before the normal Display-runtime GUI starts.
- If an activation attempt fails and state returns/remains pending, the approval waiter ensures the pending GUI service is started again.
- After healthy activation the bootstrap cleanup disables/removes the temporary GUI unit.

## Visual contract

No alternative pending screen or extra action row is introduced. `Handlinger`, `Systeminfo`, `Kioskinfo`, `Netværksinfo` and `Kalender – næste 7 dage` remain the same GTK4 implementation and legacy visual grammar. Pending state is expressed only through values and sensitivity: `Registreret / afventer godkendelse`, `Registreret – afventer godkendelse`, `Ikke aktiveret`, and disabled Start/Stop controls.

## Frozen-domain boundary

Livestream, Terminal and Remote Desktop implementations, credentials, protocols, services and sockets are unchanged. The pending GUI does not start them and does not call their control paths.
