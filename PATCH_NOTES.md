# ClientFlow A-03 + B-02 blocker fix

**Branch:** `fix/display-primary-group-stop-contract`

**Required base:** GitHub `main` commit `e39707a61782d7705c611c51b84a3e72ca1e9b9b`

This package intentionally does **not** change `client/VERSION`, release sequence, release catalog, approval metadata, or immutable 1.3.10/1211 bytes. A new release identity belongs after the remaining operational compatibility review and CI gates are complete.

## A-03 — Display Chrome crash caused by primary group

Physical isolation on clean Ubuntu 26.04 proved:

- canonical system service with `User=viborg2` + primary `Group=clientflow-display-control` crashes Chrome;
- same system manager, same Chrome/Wayland/flags, but kiosk user's passwd primary group + `clientflow-display-control` supplementary survives the full canonical hardening set (`RC=124`, browser visible);
- `MemoryDenyWriteExecute`, `NoNewPrivileges`, PAM, profile, URL, Chrome version and Wayland were separately excluded as required triggers.

Fix:

- remove `Group=clientflow-display-control` from `clientflow-display-runtime.service`;
- keep `clientflow-display-control` as a supplementary group;
- Display runtime restores group ownership/modes for only its shared state/runtime boundary;
- config/status files are atomically published with the control group **before** rename;
- runtime socket is explicitly `0660` and `clientflow-display-control`;
- Chrome profile/PID behavior remains kiosk-user-owned and is not broadened to the control group.

The new atomic helper is **Display-only** (`display_shared_file.py`). The shared `atomic.py` used by other domains is deliberately untouched to isolate Frozen-domain risk.

## B-02 — Stop disabled while runtime still retries

Physical evidence showed `chrome_running=false`/`browser_exited` while runtime retained `browser_requested=true` and retried every 5 seconds. Frontend disabled Stop solely from process absence, so no `stop_browser` command was emitted.

Fix contract:

`runtime.browser_requested` → Display status payload → backend Display projection → `/api/clients/{id}/chrome-status` → `ClientDetailsPage` → Actions policy.

Stop is disabled only when canonical `browser_requested === false`. If the process is absent but request state is `true` (failed/retry/waiting), Stop remains available. Unknown/legacy request state also does not infer that Stop is unnecessary. Backend `stop_browser` remains idempotent and clears `browser_requested` even when no child process exists.

## Frozen risk

No Livestream, Terminal or Remote Desktop agent/service source is changed. Shared `clientflow_runtime.atomic` is not changed. `backend/service1/routers/clients.py` receives only a response-only Display field projection; no Terminal/RD/Livestream route logic is altered.

Required post-release physical regression for this change is Display-specific: commissioning → browser running → Stop → Start → reboot → browser restored/reconnect. Frozen Livestream/Terminal/Remote Desktop remain read-only compatibility checks unless CI/review exposes a concrete defect.

## Tests added

- executable Display runtime permission/socket test;
- executable idempotent stop/request-state runtime test;
- backend Display projection + `/chrome-status` response contract test;
- executable frontend action policy test for `chrome_running` vs `browser_requested`.

Local pre-package checks completed:

- Python compileall: PASS for changed Python files/tests;
- Display runtime permission tests: `3 passed`;
- frontend action-policy Node tests: `4 passed`;
- generated git patch: `git diff --check` PASS;
- generated git patch: `git apply --check` PASS against verified base files.

The backend projection/HTTP test requires the repository's locked CI Python dependencies (`sqlmodel`, etc.) and is therefore expected to execute in canonical GitHub CI.
