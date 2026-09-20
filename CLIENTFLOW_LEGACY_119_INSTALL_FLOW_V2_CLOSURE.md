# ClientFlow V2 — legacy 1.1.19 install-flow parity closure

## Scope and source authority

This source package is based only on canonical V2 main commit
`169829d8c3472ddf45b82b4e2592cbb1ce1a3e56` (`ClientFlow 1.3.21 / sequence 1222`).
The runtime catalog intentionally remains `ClientFlow 1.3.20 / sequence 1221`.

This closure is source work only. It does **not** authorize runtime-input transport,
release build, approval, publication or catalog promotion for 1.3.21/1222.

The operator-process baseline is deployed legacy 1.1.19 plus the reviewed legacy
USB preparation media. V2 security/release invariants remain authoritative below
the visible flow.

## Visible operator flow

The implemented V2 flow is:

1. Start the repo-owned USB bootstrap as the ordinary Ubuntu installation user.
2. Verify the complete USB file set and payload SHA-256 manifests before privileged installation.
3. Establish/verify office network connectivity and create **01 Klient klargøring**.
4. Open **01 Klient klargøring**.
5. Confirm the client name on the office side.
6. Create **02 Aktiver ClientFlow**.
7. Remove only NetworkManager profiles that ClientFlow can prove it created itself.
8. Ask the operator before the first reboot; reboot uses the narrow inhibitor override and never `--force`.
9. At the customer, open **02 Aktiver ClientFlow** once.
10. Establish/verify customer network connectivity.
11. Show the office-defined client name and ask for optional locality/room.
12. Enter the CF code through the formatted `CF-____-____-____` editor.
13. Resolve the CF code to its exact approved release binding and authorization, then download and verify only that exact bundle.
14. Consume the canonical backend claim. A definite pre-commit 4xx returns only to CF-code entry; ambiguous transport/5xx outcomes remain resumable without reusing a consumed one-time code.
15. After the accepted claim, provision the canonical ClientFlow human accounts and ask for the `cfadmin` password directly on the controlling terminal. The password is never stored in bootstrap state.
16. Stop at durable `pending_manual_activation`, prepare only the minimum graphical login baseline and enable the narrow first-activation waiter.
17. Remove the installation icon and ask the operator before the second reboot.
18. After backend approval, the waiter invokes only the immutable staged canonical activation CLI. No second operator click is required.
19. Canonical activation re-proves backend approval before runtime mutation and retains the existing health/rollback gates.
20. After healthy activation, remove only the exact bootstrap artifacts and the exact recorded temporary bootstrap user/network marker owned by the canonical lifecycle.

## Explicit security-required legacy difference

Legacy asked for the `cfadmin` password during office preparation. V2 deliberately
does not create permanent ClientFlow human accounts before a consuming backend
claim has been accepted. The password therefore moves to customer phase 2 after
the claim trust gate and is read directly from the terminal. It is not persisted,
sealed, cached or transported merely to imitate the historical prompt order.

This is the only accepted visible ordering exception in this package.

## Security and recovery invariants retained

- No USB-side `latest` or `stable` release authority.
- Exact release selection comes only from the CF-code backend binding.
- Whole-bundle SHA-256/size and embedded-installer checks remain canonical.
- Approval proof remains fail-closed before active-symlink/systemd/runtime mutation.
- Livestream, Terminal and Remote Desktop implementation domains remain frozen.
- Network cleanup is exact-UUID and exact-name/type checked; unknown profiles are never deleted broadly.
- Privileged desktop-file creation rejects symlink substitution and requires the target to stay inside the selected user's home/XDG Desktop.
- Bootstrap state is root-owned and mode-restricted.
- Ambiguous first-claim failures retain only the already verified exact bundle root-only so the one-time CF code is not incorrectly reused.
- A crash after durable `pending_manual_activation` resumes through the product customer orchestrator, so it cannot bypass the approval waiter or the operator-confirmed reboot.
- Reboot primitive is `systemctl --no-block --check-inhibitors=no reboot`, 10-second command timeout, with no `--force`.

## USB build evidence

The repo-owned builder is `scripts/build_clientflow_usb_installer.py`.
Two independent builds from this source in the same controlled environment were
byte-identical, and both internal checksum manifests verified after extraction.

- artifact: `clientflow-v2-legacy119-usb-final.zip`
- size: `21414` bytes
- SHA-256: `872512f99df6daea5ed75f682721e2b6d79d3fb4d5ceee56934ecd712cb87ea0`

The external ZIP SHA-256 is the handoff trust anchor. The internal
`USB_SHA256SUMS.txt` and `PAYLOAD_SHA256SUMS.txt` detect changes after extraction.

## Local executable/source gates completed

The following gates were executed against the final working tree:

- `python3 -m pytest scripts/tests -q` with repo runtime/release paths on `PYTHONPATH`: **226 passed**.
- `python3 scripts/validate_dependency_contract.py`: **PASS** for the repository contract.
- `python3 scripts/verify_clientflow_legacy119_capability_gate.py --scope frontend`: **30/30 frontend proof tests passed**, gate status `ok`.
- `python3 -m compileall -q client/bootstrap client/release/lib scripts`: **PASS**.
- `bash -n client/bootstrap/usb/01_START_CLIENTFLOW_USB.sh`: **PASS**.
- USB deterministic double-build and both internal SHA-256 manifests: **PASS**.

## Gates intentionally not claimed locally

This container does not have the hash-locked backend CI environment or frontend
install tree and does not match the exact CI Node/npm versions. Therefore the
following remain mandatory GitHub gates and are **not** represented as locally
passed:

- hash-locked Python CI dependency installation and `pip check`;
- Ruff 0.15.21 static checks;
- backend tests/integration tests requiring `sqlmodel`, `passlib`, PostgreSQL and the locked CI environment;
- exact Ubuntu 26.04 host executable contracts;
- exact Node 22.22.0 / npm 10.9.4 `npm ci`, dependency audit, complete frontend tests, ESLint and production build.

Full canonical GitHub CI must be green before merge. Only after that may the
physical ClientFlow test begin, one terminal block at a time. Releaseflow for
1.3.21/1222 remains paused throughout this closure.
