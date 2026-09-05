# Production Readiness / Legacy Functional Closure — source batch 1

Branch: `fix/production-readiness-legacy-functional-closure`

Base source archive identity reviewed: `5ecf9b1f98ab25847314f3bd431e89a5909ec6c9`
New source candidate after this byte-changing batch: ClientFlow `1.3.19`, release sequence `1220`.
This is source identity only. It is NOT approved, published or catalog-promoted.

## Findings closed in this batch

### B1 — canonical human-account lifecycle, first closure slice

Evidence/root cause:
- canonical `clientflow-kiosk` was created by account provisioning but omitted from fresh-conflict detection;
- wipe removed `cfadmin` but omitted `clientflow-kiosk`;
- no exact bootstrap Ubuntu user was carried from the sudo invocation into fresh-install lifecycle state;
- therefore a previous kiosk identity could be silently reused and the temporary bootstrap account could survive production activation.

Change:
- `clientflow-kiosk` is now a fresh-install conflict and a wipe-owned ClientFlow account;
- fresh install records only the exact `SUDO_USER` when it is a normal, non-protected local user;
- healthy first activation removes only that exact recorded bootstrap user;
- `root`, `clientflow-kiosk` and `cfadmin` are protected;
- no broad enumeration/deletion of unrelated normal users was introduced.

Frozen risk:
- no Livestream, Terminal or Remote Desktop runtime/agent file changed.

### B7 — install-state / release-state lifecycle consistency

Evidence/root cause:
- successful first activation committed release-state but left `install-state.json` as `pending_manual_activation`;
- the old enrollment seed also remained after the crash/resume purpose had ended.

Change:
- after a durable healthy first activation, canonical CLI finalizes install-state to `activated`;
- original immutable `fresh_install_binding` is preserved unchanged as historical provenance;
- `activated_release_id` is recorded;
- bootstrap-user marker is cleared;
- crash/resume `credential_seed_b64` is removed after successful first activation;
- later update activations cannot rewrite the original fresh-install binding.

## Tests added

`scripts/tests/test_clientflow_human_account_lifecycle_closure.py`

Executable Python tests cover:
- exact sudo/bootstrap-user detection;
- protected account exclusion;
- exact-only bootstrap account deletion;
- protected identity refusal;
- canonical kiosk fresh-conflict detection;
- successful first-activation install-state finalization while preserving the exact original binding.

Targeted local result: `9 passed` together with the existing human-account legacy119 tests.

## Explicitly still open

This ZIP does NOT claim closure of: curl/APT preclaim bootstrap, NetworkManager/factory cleanup, pre-first-activation repair release authority, full GTK4 legacy GUI parity, periodic time integrity, quick settings, cfadmin popup parity, recovery/support UX, local power event reporters, full capability-based legacy parity gate, or frontend obsolete-contract cleanup.

Do not build/approve/publish/promote 1.3.19/1220 merely because this slice is green. Continue source closure first.
