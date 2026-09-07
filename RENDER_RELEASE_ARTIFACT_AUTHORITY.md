# Render release-artifact authority (51M)

## Finding

The v2 backend release plane resolves deployable ClientFlow bytes from
`CLIENTFLOW_RELEASE_ARTIFACT_DIR`, but the original Render mount-root contract
pointed that variable directly at the persistent disk mount.

Physical validation of the canonical v2 Render service showed that Render
creates the mount root `/var/data/clientflow-release-artifacts` as `2775`
(`root:render`). That is writable by the service group. Both
`clientflow_release_artifacts.py` and `publish_clientflow_release.py` correctly
reject any artifact directory that is group- or world-writable.

Classification: **B – deployment/runtime contract inconsistency**.

The security validation is retained unchanged. The topology instead uses a
service-owned secure child directory inside the persistent mount.

## Canonical Render contract

The `planiq-display-v2-backend` service owns the ClientFlow release artifact
store:

- service plan: `starter` (paid; persistent disks are not available on free services)
- runtime instances: exactly `1`
- persistent disk name: `clientflow-release-artifacts`
- Render disk mount root: `/var/data/clientflow-release-artifacts`
- secure artifact directory: `/var/data/clientflow-release-artifacts/store`
- initial disk size: `1 GB`
- `CLIENTFLOW_RELEASE_ARTIFACT_DIR=/var/data/clientflow-release-artifacts/store`

The Render-owned mount root may have platform-managed group-write permissions.
It is therefore not itself a valid 51M publication target. Before Uvicorn
starts, the backend start command idempotently creates the `store` child and
sets it to mode `0755`. The runtime and publication gate both use only that
child directory.

A persistent Render disk is attached to only one service instance. Therefore
this backend remains explicitly single-instance while filesystem-backed release
artifact authority is in use. This is compatible with the already locked
single-worker backend process model.

## Lifecycle boundary

Render makes persistent disks available to the running service instance, not to
the build command or pre-deploy command. Consequently:

- database migrations remain in `preDeployCommand`;
- release publication must **not** be added to `preDeployCommand`;
- the secure `store` child is created in the running-service start command,
  before the backend process starts;
- approved bundle publication happens from the running backend service context
  (for example an authorized Render Shell session) where the disk is mounted;
- publication uses only `scripts/publish_clientflow_release.py` with the exact
  approved bundle SHA-256, approval reference and source commit;
- publication targets `/var/data/clientflow-release-artifacts/store`;
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

After the v2 Blueprint is deployed, runtime validation must prove:

1. the persistent disk is mounted at `/var/data/clientflow-release-artifacts`;
2. `CLIENTFLOW_RELEASE_ARTIFACT_DIR` points to its `store` child;
3. startup creates that child before Uvicorn starts;
4. the secure child is a real directory, writable by the service process and
   not group-/world-writable;
5. the approved release can be published atomically into the secure child;
6. the artifact survives a backend redeploy/restart;
7. the backend re-resolves the same approved bundle SHA-256 afterward.

No frozen ClientFlow domain code is changed by this correction.
