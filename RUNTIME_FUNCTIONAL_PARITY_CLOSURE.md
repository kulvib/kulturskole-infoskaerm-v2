# ClientFlow 1.1.19 Runtime Functional Parity Closure

Status: source candidate for branch `fix/legacy119-runtime-functional-parity`.

This closure is intentionally limited to runtime functional parity and the cross-contracts required to make those runtime functions executable. It does **not** authorize a release or a physical fresh install. Canonical CI, reproducible build, manual approval, immutable publication and catalog promotion remain mandatory.

## Authorities and invariants

- Legacy ClientFlow 1.1.19 is the functional-behaviour authority for existing functions.
- The v2 enrollment, approval, unique credential/domain isolation and immutable whole-bundle release model remain the security/release authority.
- User-approved Display/browser UX countdown policy is 10 seconds for boot/start, URL/config change, backend/GUI start, reset and display sleep.
- Livestream, Terminal and Remote Desktop are Frozen. This batch must not change their source bytes.
- No new generic root shell or generic privileged transport is introduced. New privilege crossings are fixed-function Unix sockets.

## Closed A/B findings

### 1. Canonical kiosk identity rejected during materialization

- Classification: B, with physical A manifestation.
- Trigger: fresh-install definition materialization with canonical `clientflow-kiosk`.
- Consequence: install fails after committed claim and staged release.
- Evidence/root cause: `_validated_kiosk_user()` accepted the syntax but rejected every name beginning with `clientflow`, contradicting the canonical account definition.
- Fix: allow exactly canonical `clientflow-kiosk`; continue rejecting root/system/other `clientflow*` identities.
- Affected source: `client/release/lib/clientflow_release/transaction.py` plus regression tests.
- Frozen risk: placeholder materialization still covers Remote Desktop, but no Frozen unit/template is changed.
- Regression: executable materialization tests cover all kiosk-user placeholders.

### 2. Presence/liveness drift

- Classification: A/B.
- Trigger: normal runtime status reporting.
- Consequence: v2 could mark a healthy client offline earlier than legacy and disable operator actions prematurely.
- Root cause: 30-second report / 90-second offline policy replaced legacy 15-second / 120-second policy.
- Fix: 15-second shared status reporting and eight missed nominal reports = 120 seconds.
- Affected source: client runtime constants, backend presence calculation and tests.
- Frozen risk: domain isolation remains unchanged.

### 3. Display/browser behavioural drift

- Classification: A/B.
- Closed behaviours:
  - all five user-visible Display/browser countdowns are the approved 10 seconds;
  - backend/manual sleep is `stop browser -> countdown -> display off`;
  - clean/manual Chrome exit publishes `chrome_closed_manual` and does not auto-restart;
  - actual browser failure retains bounded crash retry;
  - bare hostnames normalize to HTTPS;
  - arbitrary remote HTTP remains rejected;
  - missing graphical session remains `waiting_session`, not a false Chrome failure.
- Root cause: v2 split browser/display authority without preserving legacy observable sequencing, and conflated session readiness with post-launch protection failure.
- Affected source: Display runtime/agent/local control, backend Display projection, frontend readiness contract and tests.
- Frozen risk: none; Frozen domains are not touched.

### 4. Chrome early-render protection lost

- Classification: A/B.
- Trigger: first kiosk navigation, reload or new frame.
- Consequence: cookie/consent/browser overlays can appear before the ongoing Browser Guard has attached.
- Root cause: legacy used document-start/all-frame extension CSS; v2 retained only the later DevTools Browser Guard layer.
- Fix: controlled navigation gate. Chrome starts at `about:blank`; CDP `Page.addScriptToEvaluateOnNewDocument` installs the early protection before `Page.navigate` to the kiosk URL. Failure is fail-closed. Browser Guard remains the ongoing protection layer.
- Best-practice basis: Chrome DevTools Protocol documents evaluate-on-new-document before frame scripts. A separately force-installed extension/update channel was rejected because it would create avoidable parallel update authority.
- Affected source: `display_runtime.py` and executable parity tests.
- Frozen risk: none.

### 5. Calendar lifecycle drift and incorrect test oracle

- Classification: A/B.
- Trigger: schedule baseline, OFF enforcement or real OFF->ON wake.
- Consequence: v2 could start browser directly rather than reproduce proven wake/reboot behaviour; old tests explicitly required the wrong no-reboot semantics.
- Root cause: replacement Calendar logic preserved intent but not legacy state-machine semantics.
- Fix:
  - 90-second boot grace;
  - backend poll 15 seconds;
  - scheduler evaluation tick 30 seconds;
  - first-state baseline without synthetic ON reboot;
  - startup OFF enforcement;
  - real OFF->ON wake followed by 15-second delayed controlled reboot;
  - 300-second reboot cooldown with browser-start fallback;
  - boot-scoped manual override until next real schedule boundary.
- Privilege boundary: new `clientflow-calendar-reboot-broker` accepts only a fixed reboot operation over a root-owned Unix socket; Calendar receives no System credential or generic root access.
- Reboot uses `--ignore-inhibitors`, matching the proven legacy appliance behaviour for Calendar/manual reboot.
- Frozen risk: none.

### 6. System power and Ubuntu update drift

- Classification: A/B.
- Trigger: backend reboot/shutdown or Ubuntu OS update requiring reboot.
- Consequence: Chrome/status sequencing could be skipped; OS update could be reported complete before a required reboot was actually observed; older v2 policy explicitly suppressed automatic reboot.
- Root cause: fixed-function v2 broker was secure but did not preserve legacy graceful lifecycle, and `systemctl --no-block` can return after enqueue rather than after the physical boot boundary.
- Fix:
  - graceful power preparation: stop Chrome -> publish shutdown step -> 5 s -> publish final power step -> 5 s;
  - Ubuntu helper: `apt update -> full-upgrade -> autoremove`;
  - helper only reports `CLIENTFLOW_REBOOT_REQUIRED`, never invokes systemctl itself;
  - System broker stores durable `reboot_requested` state and pending update result before crossing the boot boundary;
  - update reboot uses a blocking fixed-function reboot request and must never return pre-boot success;
  - backend command payload is bound to the Status boot-id at request time;
  - after Status reports a different boot-id, the exact same claimed update command is requeued/reclaimed and the broker completes from its durable journal without re-running APT.
- Best-practice basis: current `systemctl(1)` documents that `--no-block` only verifies/enqueues; Ubuntu documents automatic reboot after reboot-required as a supported update policy.
- Affected source: System broker, update helper, backend shared-command reconciliation/routes, System tests and new CI integration test.
- Frozen risk: none.

### 7. Optional Kiosk lockdown missing / wrong v2 default

- Classification: A/B.
- Trigger: superadmin toggles Kiosk lockdown.
- Consequence: v2 had durable DB fields but rejected the function; an intermediate implementation also incorrectly made full lockdown an activation default.
- Root cause: legacy optional function was removed from the executable v2 control path and confused with the normal kiosk security baseline.
- Fix:
  - default remains OFF;
  - superadmin desired boolean is durable backend authority;
  - reconciliation uses the existing Display command domain;
  - root-owned fixed-function broker accepts only `enabled=true|false` and loads canonical kiosk identity locally;
  - apply/rollback dynamically masks/restores desktop launchers, applies/removes kiosk-only ACL/polkit/GSettings and manages the two-second quick-settings guard;
  - terminal `applied` state is published only after systemd accepted the guard;
  - local recovery unlock is physical rollback only; backend desired-state may later reconcile it back on;
  - `desktop_lockdown_last_applied_at` changes on actual transition/command completion, not every heartbeat.
- Best-practice basis: GNOME lockdown guidance explicitly notes UI lockdown does not replace authorization; ACL/polkit remain separate enforcement layers.
- Frozen risk: none.

### 8. Session/popup suppression incomplete

- Classification: A/B.
- Trigger: kiosk/cfadmin graphical sessions and crash/browser popup conditions.
- Consequence: legacy-suppressed OS/browser prompts could reappear.
- Root cause: v2 carried only a reduced subset of legacy popup policy.
- Fix: system-wide Apport suppression, broader managed Firefox policy, `user.js` for existing kiosk/cfadmin Firefox profiles, popup autostart overrides and known popup-process cleanup while preserving the optional lockdown separation.
- Best-practice basis: Ubuntu Apport and Mozilla enterprise policy mechanisms are used rather than adding a new ad-hoc privilege channel.
- Frozen risk: none.

### 9. Local recovery and Local GUI parity gaps

- Classification: A/B.
- Trigger: local maintenance/support.
- Consequence: proven legacy `unlock`/menu and operational status fields were missing.
- Fix:
  - recovery surface: `status|unlock|restart|bundle|menu`;
  - Local GUI restores Backend sync, Calendar service, client status, current resolution, backend-selected resolution, display status and explicit sleep state;
  - GUI reads only local non-secret runtime/materialized state and receives no backend credential.
- Frozen risk: none.

## Test-oracle corrections

The review found several tests that had become authorities for replacement behaviour rather than legacy functional behaviour. This batch changes the oracle together with implementation where evidence showed the oracle was wrong, including Calendar no-reboot assumptions, optional-lockdown removal/default, display labels and System update no-reboot assumptions.

A new DB-dependent operational test is added for the OS-update reboot-resume backend chain: boot A claim -> boot B Status reconnect -> same command requeue/reclaim -> completion with recovered boot evidence. The local broker journal recovery is separately executable-tested to prove no second APT execution is needed.

## Local verification performed on this source candidate

The final exact counts must be regenerated after hygiene cleanup. At the latest pre-cleanup gate:

- `scripts/tests`: 184 passed.
- backend source/isolation tests: 130 passed.
- frontend readiness contract: 7/7 passed.
- legacy capability validate: 13/13 capabilities, 177/177 inventory, status OK.
- Python compileall: passed.
- relevant Bash syntax: passed.
- Frozen path hash comparison: 73 matched paths, zero byte drift.

Environment limitations are explicit, not treated as PASS:

- local Python is 3.13.5 while the runtime project requires 3.13.14;
- `sqlmodel` and `passlib` are absent locally, so DB-backed HTTP integration tests cannot collect here;
- locked Ruff 0.15.21 is absent locally;
- the container cannot resolve/download the locked CI environment from PyPI;
- frontend `node_modules` is absent, so full npm lint/build is canonical-CI gated.

Canonical CI therefore remains mandatory before merge. Green local source gates are necessary but not sufficient.

## Frozen verification requirement

Before packaging and after all cleanup, SHA-256 comparison against the fresh-main baseline must show zero changed/missing paths for Livestream, Terminal and Remote Desktop. Any non-zero drift invalidates this candidate.

## Explicitly outside this batch

The following known necessary fresh-install/release work remains a separate architecture batch and is not silently mixed into runtime parity:

- customer-oriented USB/fresh-install UX with short human enrollment code while retaining exact signed immutable release binding;
- durable exact enrollment-to-release binding without `latest` authority;
- exact ownership/cleanup of temporary factory NetworkManager connection UUID;
- any required DB migration for that fresh-install capability;
- reproducible new release build, manual approval, immutable publication to canonical Render 51M store and catalog promotion.

No physical fresh install is authorized by this closure alone.

## Final local verification — 2026-09-07

Candidate branch identity: `fix/legacy119-runtime-functional-parity`.

Verified against the fresh uploaded v2 main baseline. Generated caches were removed before the final diff.

Local executable/source gates available in this environment:

- `scripts/tests`: 184/184 PASS.
- affected backend source/system contracts: 40/40 PASS.
- frontend readiness UI contract: 7/7 PASS.
- release build/procedure contracts: 13/13 PASS.
- Python `compileall`: PASS.
- changed shell helpers `bash -n`: PASS.
- canonical Frozen v2 source files for Livestream/Terminal/Remote Desktop: 12 checked, 0 byte drift.

DB-backed backend integration tests that require `sqlmodel` could not be collected in this local container and are not claimed as PASS; canonical CI remains required before merge.
