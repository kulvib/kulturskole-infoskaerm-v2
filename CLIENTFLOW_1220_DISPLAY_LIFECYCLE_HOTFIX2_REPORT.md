# ClientFlow 1.3.19 / sequence 1220 — Display lifecycle hotfix 2

## Purpose

This hotfix closes an incomplete part of `CF-1220-DISPLAY-01` discovered during
release-readiness review after the physical-harvest fix branch had been merged.
It is based on fresh `main` commit:

`e7aca1ae13a29fd991e17657001bc9204d17d7d0`

The source/build identity deliberately remains:

- version: `1.3.19`
- release sequence: `1220`
- selected runtime catalog: `clientflow-1.3.19-seq-1220`

`1.3.20 / 1221` must not be allocated until this hotfix has passed canonical
GitHub CI on its own commit.

## Confirmed lifecycle gap

The first physical-harvest fix queued a controlled pre-activation reboot after
durable `pending_manual_activation`, but GDM/autologin was still only
materialized by `clientflow-display-platform-prepare` during activation. That
ordering could reboot before `/etc/gdm3/custom.conf` and AccountsService were
prepared for `clientflow-kiosk`, leaving the required kiosk Wayland session
absent and reproducing the original first-activation Display readiness failure.

## Fix

A new staged-runtime module:

`client/runtime/clientflow_runtime/display_session_prepare.py`

owns the narrow pre-reboot login materialization. It calls only the new
`prepare_graphical_login_baseline()` boundary in `display_platform_prepare.py`.
That boundary validates the kiosk account/home and materializes only:

- GDM autologin / Wayland configuration;
- AccountsService Ubuntu-session configuration.

It deliberately does **not**:

- install or change Chrome;
- start ClientFlow runtime services;
- switch `/opt/clientflow/active`;
- enable `clientflow.target` or the updater timer;
- apply system kiosk policy;
- weaken activation health;
- mutate Livestream, Terminal or Remote Desktop implementations.

The outer `Aktiver ClientFlow` bootstrap invokes this module through the
immutable staged runtime Python only after durable `pending_manual_activation`
exists. Only after successful login-baseline preparation does it queue the
controlled reboot.

If a later pending invocation finds that no canonical `clientflow-kiosk`
seat0 Wayland session exists, it repeats the idempotent login preparation and
reboot instead of attempting activation. When the session exists, ordinary
first activation still uses the immutable staged `clientflow_release activate`
path and retains the existing backend approval/health/rollback gates.

## Documentation closure

The canonical release procedure and installation guide are corrected so they
no longer state that ordinary first activation dispatches through the stable
updater or transient `/run` installer. They now describe the staged runtime
login-preparation boundary and staged canonical activation CLI.

## Validation completed locally

- Python compileall for backend/client/scripts: **PASS**
- focused lifecycle/physical-fix/display/procedure tests: **42/42 PASS**
- canonical ClientFlow minimum release gate plus touched tests: **70/70 PASS**
- source identity remains `1.3.19 / 1220`: **PASS**
- runtime catalog remains `1.3.19 / 1220`: **PASS**
- frozen implementation domains changed: **none**

Local full `backend/tests + scripts/tests` was not claimed because this analysis
container does not contain the repo-locked CI dependencies (`sqlmodel`,
`passlib`, etc.). Those dependencies must be supplied by the canonical GitHub
CI workflow; they were not installed ad hoc.

Local Ruff execution was also not claimed because the repo-pinned Ruff binary is
not installed in this container. GitHub CI remains the formatting/lint gate.

## Next gate

Apply this hotfix on a fresh branch from the exact main baseline above and run
all canonical GitHub CI jobs. Only after that commit has a green **push** CI run
may the separate staged source-identity transition to `1.3.20 / sequence 1221`
be created.
