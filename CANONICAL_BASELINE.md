# ClientFlow canonical baseline

This repository is a consolidated source baseline built on 2026-08-19 from:

- the latest reviewed backend/frontend repository; and
- the physically validated Ubuntu runtime `/opt/clientflow/releases/clientflow-1.2.0-seq-1200`.

## Canonical runtime

`client/` is the source representation of the physically validated 1.2.0 runtime.
The systemd units are taken from the installed `/etc/systemd/system` state, because
that is the physical source of truth for the producer and Remote Desktop capture
units that differed from the older packaged copies.

## Retired

- all 1.1.x installer artifacts and signed multi-version release history
- Terminal, Remote Desktop and Livestream overlay installers
- Livestream v1/shared-mailbox transport
- `pending_livestream_action` and `pending_livestream_action_source`
- `livestream_control_plane_version` branching
- compatibility `/api/clients/{id}/livestream-command`
- Livestream aliases through the generic Chrome command endpoint
- legacy Livestream upload/cleanup/viewer/WebSocket endpoints
- historical support-terminal commands targeting old ClientFlow services/paths
- unused `client.school` compatibility column

## Database history

The reviewed Alembic history through v49 is retained intentionally as schema
history, not active runtime compatibility. Revision 50A removes the retired
runtime compatibility columns from existing databases. A future migration
squash can be performed only after a fresh-database + existing-database parity
run proves the new baseline.

## Release artifacts

Large offline Python runtime/wheel binaries are intentionally not committed to
source. `client/runtime-artifacts.lock.json` records the exact physically
validated artifact hashes. Binary publication belongs to the release artifact
store/build pipeline.
