# Canonical v2 change/release checklist

This checklist is for the current correctness/isolation phase. Production-readiness governance is a separate later phase.

## Source change

- [ ] Change is tied to a documented category A/B finding, or is explicit removal of stale category D material.
- [ ] Root cause and affected contract are documented.
- [ ] Frozen Livestream/Terminal/RD behavior is unchanged unless the finding explicitly opens that domain.
- [ ] No credentials, tokens, private keys, database URLs or local state are committed.
- [ ] No `__pycache__`, `*.pyc`, build output or runtime binary artifacts are committed as source.

## Database

- [ ] Alembic revision id fits `alembic_version.version_num` (`VARCHAR(32)`).
- [ ] Existing schema/data assumptions were checked before destructive changes.
- [ ] Fresh-database and existing-database paths converge on the same schema contract.
- [ ] Historical migrations are not rewritten without an explicit migration-chain reason.
- [ ] `python backend/scripts/validate_display_baseline.py` is green in the backend test environment.

## Backend/frontend contracts

- [ ] Relevant source-contract tests are green.
- [ ] Backend ↔ database and backend ↔ client payload fields/types/optionalities match.
- [ ] Frontend build/tests are green when frontend code changed.

## Client release/install

- [ ] `client/VERSION` and `client/release/release-input.json` are intentional.
- [ ] Canonical runtime wheel is built from `client/runtime/`.
- [ ] Release candidate builds with the approved offline runtime inputs.
- [ ] Candidate is `deployable: false` before approval.
- [ ] Candidate manifest binds the exact fresh-installer file name, size and SHA-256.
- [ ] Approval is bound to exact candidate SHA-256, source commit and fresh-installer SHA-256.
- [ ] Approval reads hash/manifest/payload from one pinned candidate file identity; candidate pathname replacement cannot change promoted bytes.
- [ ] Approved bundle verifies with its exact whole-bundle SHA-256.
- [ ] Backend publication streams from the same pinned approved-bundle identity that was verified and uses atomic no-replace publication into a pinned secure artifact directory.
- [ ] Manifest schema 8 embeds the exact fresh-installer bytes inside the approved bundle; no loose installer path is a release authority.
- [ ] Before any installer code executes, the canonical host-bootstrap verifies one pinned approved-bundle identity, extracts the embedded installer from that same open bundle, and materializes root-owned private bundle/installer copies under `/run`.
- [ ] Installer/systemd/sysusers/tmpfiles inputs are present in the generated payload.
- [ ] Kiosk-user-dependent definitions are rendered from the installation identity, not hardcoded to one physical host.

## Physical regression gate

If runtime/install/systemd/auth behavior changed:

- [ ] relevant Ubuntu fresh-install/update path is tested
- [ ] reboot/boot wiring is checked when service definitions changed
- [ ] Display/Status/System shared control-plane regression is run for shared-foundation changes
- [ ] Livestream regression is run if its provisioning/systemd/runtime boundary changed
- [ ] Terminal standard + admin/root regression is run if its provisioning/systemd/auth boundary changed
- [ ] Remote Desktop viewing/input regression is run if its provisioning/systemd/runtime boundary changed

Do not replace a known-good physical client before the candidate release has passed the required regression gate.
