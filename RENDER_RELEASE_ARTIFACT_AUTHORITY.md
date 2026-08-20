# Render release-artifact authority (51M)

## Finding

The v2 backend release plane resolves deployable ClientFlow bytes from
`CLIENTFLOW_RELEASE_ARTIFACT_DIR`, but the previous Render Blueprint did not
provision persistent storage or bind that environment variable. Render runtime
filesystems are otherwise ephemeral, so a locally published approved bundle
would not be a durable backend authority across deploys/restarts.

Classification: **B – deployment/runtime contract inconsistency**.

## Canonical Render contract

The `infoskaerm-backend` service owns the ClientFlow release artifact store:

- service plan: `starter` (paid; persistent disks are not available on free services)
- runtime instances: exactly `1`
- persistent disk name: `clientflow-release-artifacts`
- disk mount path: `/var/data/clientflow-release-artifacts`
- initial disk size: `1 GB`
- `CLIENTFLOW_RELEASE_ARTIFACT_DIR=/var/data/clientflow-release-artifacts`

The disk and environment path are one contract and must never diverge.

A persistent Render disk is attached to only one service instance. Therefore
this backend remains explicitly single-instance while filesystem-backed release
artifact authority is in use. This is compatible with the already locked
single-worker backend process model.

## Lifecycle boundary

Render makes persistent disks available to the running service instance, not to
the build command or pre-deploy command. Consequently:

- database migrations remain in `preDeployCommand`;
- release publication must **not** be added to `preDeployCommand`;
- approved bundle publication happens from the running backend service context
  (for example an authorized Render Shell session) where the disk is mounted;
- publication uses only `scripts/publish_clientflow_release.py` with the exact
  approved bundle SHA-256, approval reference and source commit;
- the publication script retains its existing secure-directory, pinned-file,
  re-hash and atomic no-replace contract.

The artifact store is backend release infrastructure. It is not shared with HLS,
Livestream, Terminal or Remote Desktop state.

## Deployment consequence

A Render service with a persistent disk cannot use multiple instances and does
not receive zero-downtime instance swaps. This is an accepted property of the
current single-instance v2 architecture, not a frozen-domain behavior change.

If the backend later needs horizontal scaling or zero-downtime deployment, the
release artifact authority must first move to a storage design that supports
multi-instance access. Do not silently remove the disk or point
`CLIENTFLOW_RELEASE_ARTIFACT_DIR` at ephemeral storage.

## Validation

CI locks this wiring in
`scripts/tests/test_render_release_artifact_contract_51m.py`.

After the v2 Blueprint is actually deployed, runtime validation must prove:

1. the environment variable equals the mounted path;
2. the mount exists and is a real directory;
3. ownership/mode satisfy `clientflow_release_artifacts.py`;
4. the approved release can be published atomically;
5. the artifact survives a backend redeploy/restart;
6. the backend re-resolves the same approved bundle SHA-256 afterward.

No frozen ClientFlow domain code is changed by 51M.
