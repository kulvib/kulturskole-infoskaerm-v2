# ClientFlow canonical v2 baseline

This repository represents the consolidated ClientFlow v2 source baseline derived from the reviewed web application and the physically validated Ubuntu ClientFlow 1.2.0 runtime.

## Canonical boundaries

- `backend/` and `frontend/` contain the current application contracts.
- `client/runtime/` is the source representation of the validated runtime.
- `client/systemd/` represents the validated service topology; host-specific values that must vary on fresh installation are rendered by the installer.
- `client/release/`, `client/sysusers.d/` and `client/tmpfiles.d/` are the canonical release/install source.
- Runtime binaries are external release inputs. `client/runtime-artifacts.lock.json` retains the physically validated historical 1.2.0 set, while the current source-independent platform inputs used for canonical release builds are separately pinned in `client/release/runtime-platform-inputs.lock.json`.

## Domain ownership

Status, Display and System use the shared domain control plane. Livestream, Terminal and Remote Desktop use isolated credentials/state and must not fall back through shared legacy transport.

## Database history

Reviewed Alembic history is retained as migration history. The canonical foundations migration removes retired runtime columns/shared Livestream ownership while adopting the physically proven enrollment/system-key tables. Migration history is not rewritten merely to make the repository look newer.

## Validation status

The repository is a canonical source candidate until its release/install path and any changed shared-foundation contracts have passed the required tests. Physically validated runtime domains remain protected as frozen baselines.
