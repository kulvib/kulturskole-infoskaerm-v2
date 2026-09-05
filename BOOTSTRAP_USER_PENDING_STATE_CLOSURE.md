# ClientFlow bootstrap-user pending-state closure

Branch: `fix/bootstrap-user-pending-state-closure`

Base fresh-main archive SHA256: `72bf46f8abcfc1df27a4e67d1b4ed5966356262867a19b8c4eb867901b8efdd7`
Client VERSION: `1.3.18`
Release sequence: `1219`
Catalog authority remains `1.3.17 / 1218`.

## Category B finding

The earlier human-account lifecycle closure recorded the exact pre-ClientFlow
Ubuntu bootstrap user in the resumable install state. However, when fresh install
transitioned to the durable `pending_manual_activation` state, `install_fresh()`
rebuilt `install-state.json` without `bootstrap_user`.

Consequence: healthy first activation called
`_finalize_install_state_after_activation()`, but no longer had the exact
bootstrap identity to pass to `cleanup_bootstrap_user()`. The temporary Ubuntu
bootstrap/install user could therefore survive activation.

## Root cause

The final pending-state dictionary copied binding/install/backend/kiosk fields
but omitted `bootstrap_user`.

## Change

`_pending_manual_activation_state()` now carries the exact recorded
`bootstrap_user` across the pending boundary. The enrollment crash/resume seed
is still intentionally dropped from the durable pending state. Healthy first
activation remains the only point that consumes and clears the bootstrap-user
marker.

No release identity, catalog, migration, updater authority, service definition,
Livestream, Terminal or Remote Desktop code is changed.

## Regression

- executable state-transition test proves exact bootstrap identity survives
  `pending_manual_activation`;
- existing activation-finalization test proves the original fresh binding is
  preserved and the bootstrap marker is cleared after healthy activation;
- full `scripts/tests` regression passes locally.
