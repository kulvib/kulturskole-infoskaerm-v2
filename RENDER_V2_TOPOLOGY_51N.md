# Canonical Render v2 topology and fresh-install entrypoint (51N)

## Status and scope

51N defines the new Render topology directly from the canonical v2 repository.
It is not a migration of the historical Render `autoinstall` topology and it
does not introduce a second release or artifact authority.

The frozen Livestream, Terminal and Remote Desktop implementations are not
changed by 51N. Their deployment configuration is preserved where the current
runtime contract requires it.

## Authorities

The topology has four distinct authorities:

1. GitHub `main` is canonical source after the reviewed 51N change is merged.
2. Neon is the PostgreSQL database authority. Render provisions no database.
3. The backend's 51M persistent disk is the authority for published approved
   ClientFlow bundle bytes.
4. The release catalog selects policy. It never replaces the exact 51M bytes or
   51H/51I approval provenance.

A fresh-install authorization is a short-lived signed capability, not a release
artifact. It records one exact already-verified 51M release identity and is
bound to one existing enrollment token. The capability cannot create, replace
or approve release bytes.

## Render resources

`render.yaml` declares one Blueprint authority with two new resources:

- `planiq-display-v2-backend`
  - web service
  - region `frankfurt`
  - `starter`
  - exactly one instance
  - exactly one Uvicorn worker
  - custom domain `api.display.planiq.dk`
  - 51M disk `clientflow-release-artifacts`
  - mount `/var/data/clientflow-release-artifacts`
  - secure 51M child `/var/data/clientflow-release-artifacts/store`
- `planiq-display-v2-frontend`
  - static runtime using current Blueprint syntax (`type: web`, `runtime: static`)
  - custom domain `display.planiq.dk`
  - same-origin HTTP rewrites to `api.display.planiq.dk`
  - direct WebSocket origin `https://api.display.planiq.dk`

There is no `databases:` resource in the Blueprint.

The Render-managed mount root is not used directly as the 51M artifact
directory. Physical validation showed that Render creates it with mode `2775`,
while the existing 51M security contract correctly rejects group-/world-writable
artifact directories. The backend start command therefore creates the `store`
child and sets mode `0755` before Uvicorn starts. `CLIENTFLOW_RELEASE_ARTIFACT_DIR`
points only to that secure child.

## Neon contract

`DATABASE_URL` is a Render secret and points to Neon. Database migrations remain
`python scripts/run_migrations.py` in `preDeployCommand`.

`MIGRATION_ALLOW_EMPTY_DATABASE=false` is the canonical Render default. 51N does
not guess that an existing Neon database is empty. Deliberate initialization of
a verified empty database remains a separate explicit migration operation.

## 51M artifact publication remains unchanged

A newly provisioned backend has an empty persistent artifact disk. The Blueprint
must not publish a release in build or pre-deploy because the disk is runtime
state.

Transport the already-approved bundle to an authorized shell on the running
backend and publish it only with the existing gate:

```bash
python scripts/publish_clientflow_release.py \
  /path/to/clientflow-1.3.0-seq-1201-approved.tar \
  --artifact-dir /var/data/clientflow-release-artifacts/store \
  --expected-bundle-sha256 <EXACT_APPROVED_BUNDLE_SHA256> \
  --expected-approval-reference <EXACT_APPROVAL_REFERENCE> \
  --expected-source-commit <EXACT_SOURCE_COMMIT> \
  --publish-release
```

The transport location is not an authority. The publication script reopens and
verifies the approved bundle and publishes atomically under 51M.

## Fresh-install authorization

Creating `POST /api/admin/enrollment-tokens` now fails closed unless the
catalog's `default_install_version`:

- is selectable;
- is `installable: true`;
- declares `fresh_install`;
- exists as an approved, deployable 51M artifact whose manifest also declares
  `fresh_install`.

The response returns the one-time enrollment code together with:

- release id/version/sequence;
- approved bundle SHA-256 and size;
- release approval reference;
- approved candidate SHA-256;
- source commit;
- a signed `fresh_install_authorization` capability.

The capability uses a dedicated 32-byte deployment signing key from
`CLIENTFLOW_FRESH_INSTALL_AUTH_KEY_B64`. The Blueprint generates this secret for
the new backend. Its payload is bound to the enrollment-token id and the same
expiry as the one-time code.

No capability or code is logged in cleartext. The audit log records only the
release/provenance metadata already suitable for audit.

## Fresh artifact download

The Ubuntu handoff calls:

`POST /api/enrollment/fresh-install-artifact`

with:

- the one-time enrollment code;
- the signed fresh-install authorization;
- the externally handed-off expected release id;
- the externally handed-off approved bundle SHA-256.

The backend requires the enrollment token to still be unused, unrevoked and
unexpired. It then verifies the capability signature and binding, reopens the
exact 51M bundle with `fresh_install` manifest validation, compares the complete
immutable provenance, and streams from the same verified open file handle.

Downloading does **not** consume the enrollment code. The existing
`/api/enrollment/claim` transaction remains the only step that consumes the code
and provisions the established domain/update credentials.

## 51I handoff remains the installer trust boundary

The admin UI provides a copyable Ubuntu block that downloads the exact bundle
and checks its externally handed-off whole-bundle SHA-256. No installer code is
run by that transport block.

After the SHA check, continue with `CLIENTFLOW_RELEASE_PROCEDURE.md` section 4:

1. open the exact downloaded bundle once under root;
2. verify the whole approved bundle SHA-256;
3. extract the embedded schema-8 fresh installer from the same pinned bundle;
4. verify the embedded installer descriptor;
5. run the existing installer with the exact bundle, backend URL and one-time
   enrollment code;
6. stop at `pending_manual_activation`;
7. approve that exact pending client through the existing canonical backend approval flow;
8. activate separately with the exact release approval reference; first activation re-proves backend approval with the provisioned Status credential before local mutation.

51N does not add a loose installer, GitHub release selector, `latest` URL,
external autoinstall service or automatic activation.

## Initial provisioning order

For a blank Render workspace using an existing Neon database:

1. create the Blueprint resources from canonical v2;
2. configure `DATABASE_URL` and all required existing runtime secrets;
3. allow pre-deploy to verify/migrate Neon through the existing fail-closed
   migration runner;
4. allow service startup to create/normalize the secure 51M `store` child;
5. if the database has no administrator, run the existing explicit/manual
   `backend/scripts/bootstrap_superadmin.py` contract;
6. publish the already-approved ClientFlow bundle into the secure 51M child;
7. verify persistence across backend restart/redeploy;
8. create a new installation code in Control Room;
9. copy the fresh-install handoff to the Ubuntu host;
10. download and hash the exact approved bundle;
11. continue through the existing 51I install and manual activation procedure.

## Runtime validation after deployment

51N is not physically accepted merely because CI is green. On the new Render
workspace verify at minimum:

- backend resource region is Frankfurt;
- both custom domains resolve to the intended new resources;
- browser HTTP remains same-origin through `/api/*` rewrites;
- browser WebSocket connections use `api.display.planiq.dk`;
- Neon `/health/db` is ready at the expected schema head;
- the 51M persistent mount exists;
- the secure 51M child exists with the required ownership/mode and is the
  configured `CLIENTFLOW_RELEASE_ARTIFACT_DIR`;
- the approved artifact survives restart/redeploy with the same SHA-256;
- enrollment-code creation fails when the approved artifact is absent;
- a valid code/capability downloads the exact approved bundle;
- revoked/expired/used codes cannot start a new download;
- the download does not consume the code before `/enrollment/claim`;
- the existing physical fresh-install/activation procedure succeeds;
- relevant shared/frozen regressions are run if deployment changes expose a
  common-infrastructure issue.
