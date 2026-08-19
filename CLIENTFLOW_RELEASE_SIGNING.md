# ClientFlow signed release catalog procedure

ClientFlow 1.1.19 uses one RSA-PSS/SHA-256 signed release catalog:

```text
clientflow-autoinstall-site/clientflow_release_catalog_signed.json
```

The same bytes are bundled with the backend at:

```text
backend/service1/clientflow_release_catalog_signed.json
```

The catalog is the only authority for factory installation, Control Room version choices and ClientFlow self-update. The old unsigned `clientflow_version.json` bootstrap is forbidden.

## Version and sequence model

Three independent values must never be conflated:

- `version`: the software version, for example `1.1.18`.
- `release_sequence`: immutable sequence attached to one release artifact.
- `catalog_sequence`: monotonically increasing signed catalog generation.
- `deployment_sequence`: monotonically increasing per-client update/rollback order created by the backend.

A deliberate rollback may lower `version`, but it must always increase the per-client `deployment_sequence`. Old signed catalogs and already processed deployment orders are rejected.

## Release status

Each catalog entry has one of these statuses:

- `stable`: current default for new installations and `latest` updates.
- `supported`: selectable installation/rollback target.
- `deprecated`: retained metadata, not installable or updateable.
- `blocked`: security- or compatibility-blocked metadata, never installable or updateable.

ClientFlow 1.1.12 is deprecated and its installer is removed because the immutable factory payload contains inconsistent release metadata. Existing bootstrap-rettede 1.1.12 clients may update forward through a supported path, but 1.1.12 is not an installation or rollback target. ClientFlow 1.1.16 is deprecated after its physical pilot exposed self-update permissions and version-integrity defects; its installer is removed. ClientFlow 1.1.15 remains the supported Ubuntu 26.04 predecessor, and ClientFlow 1.1.11 remains the historical Ubuntu 24.04 factory/rollback target. ClientFlow 1.1.9 is deprecated. ClientFlow 1.1.8 is blocked because root-services could execute from a `clientflow`-writable runtime path; its installer must not be published.

## Secret handling

The encrypted private signing key and passphrase must never be committed, uploaded to Render, copied into an installer or placed on an infoskærm. Only `clientflow_update_pubkey.pem` is public.

Keep at least two controlled offline backups of the private key and keep the passphrase separately.

## Future release procedure

1. Build a new immutable installer with a new semantic `version`, `revision`, `client_version_patch` and higher `release_sequence`.
2. Compute the exact installer `sha256`, `size` and payload hash.
3. Add the release to `clientflow_release_catalog_signed.json` with compatibility metadata:
   - `min_current_version`
   - `max_current_version`
   - `ubuntu_versions`
   - `rollback_allowed`
   - `installable` and `update_allowed`
4. Increase `catalog_sequence`; never reuse a previous sequence.
5. Keep only approved factory-installable or signed update/rollback artifacts on the autoinstall site. Blocked and deprecated releases retain metadata only.
6. Sign the catalog:

```bash
python scripts/sign_clientflow_manifest.py \
  clientflow-autoinstall-site/clientflow_release_catalog_signed.json \
  --private-key /secure/path/clientflow_manifest_signing_private.pem \
  --public-key clientflow-autoinstall-site/clientflow_update_pubkey.pem \
  --passphrase-file /secure/path/clientflow_signing_key_passphrase.txt
```

7. Copy the signed catalog byte-for-byte to `backend/service1/clientflow_release_catalog_signed.json`.
8. While legacy clients still consume the schema-2 bridge, update and sign `clientflow_version_signed.json` as a legacy forward-only bridge to `latest_stable`, then copy it to `expected_clientflow_version.json`.
9. Regenerate `SHA256SUMS.txt` and run all repository, ClientFlow, backend and frontend tests.
10. Deploy catalog, backend copy and installers in the same commit. Smoke-test one client before broad rollout.

## Controlled rollback

A rollback must:

- target a `supported` release with `rollback_allowed: true`;
- be requested by a superadministrator;
- include explicit confirmation and a reason;
- create a new, higher `deployment_sequence`;
- be written to the audit log as a critical action;
- pass current-version and Ubuntu compatibility checks in both backend and client.

Automatic rollback after an installer failure is a separate local recovery mechanism and does not alter deployment policy.

## Key rotation

Key rotation requires a release signed by the currently trusted key that installs the next public key and changes the expected key ID. If the current private key is lost, clients require controlled manual recovery.

## Permanent runtime boundary

All signed releases must keep `/opt/clientflow/venv` and `/usr/local/lib/clientflow-root` root-owned. Root-services must never execute code or an interpreter from `/opt/clientflow/api`.

## Ubuntu platform contract

The current ClientFlow platform baseline is Ubuntu Desktop LTS 26.04 or newer on `amd64` with GNOME Wayland. Ubuntu 26.04 is the maximum certified version for ClientFlow 1.1.19; future LTS releases may proceed only after the mandatory signed capability preflight succeeds. Historical releases continue to use exact `ubuntu_versions`. An existing immutable installer must never be relabelled for a different compatibility policy.


## ClientFlow 1.1.16 archive and request identity hardening

The signed installer must validate archive paths without character-based stripping. A legitimate TAR root directory may be accepted only as a directory; absolute paths, traversal, Windows drive paths, duplicate members, links and special files are rejected. The production payload omits the redundant root member for forward compatibility. Update-request deduplication is keyed primarily by the backend-issued monotonic deployment sequence, with the backend request timestamp retained as request metadata.

## ClientFlow 1.1.19 self-update permissions and version integrity

The installer identity is immutable: `1.1.18`, `v1.1.19_livestream_state_cadence_update_integrity`, `release_v1_1_19_livestream_state_cadence_update_integrity`, sequence `1118`. Caller-provided target fields may supply authorization context, but they must never redefine the release artifact identity.

Every factory and self-update path must enforce these postconditions:

- `/opt/clientflow/venv` is owned by `root:root`, is not group/other writable, and remains traversable/executable by the `clientflow` service user despite the updater service using `UMask=0077`.
- `/opt/clientflow/api` is owned by `clientflow:clientflow`; configuration and runtime JSON files support atomic replace without becoming root-only.
- `/etc/clientflow/clientflow.env` is atomically updated with the exact version and patch and remains `root:clientflow` mode `0640`.
- Static `05-clientflow-version.conf` drop-ins are removed so the environment file is the single version authority.
- A post-update integrity oneshot runs after the legacy updater process has completed its final root writes.
- Rollback preserves the previous venv and environment state until post-update verification succeeds.

The release tests must exercise these contracts from the packaged installer, not merely inspect repository source files.
