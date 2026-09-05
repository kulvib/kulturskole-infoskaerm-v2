# ClientFlow pre-first-activation repair closure

## Classification

**B – lifecycle/update authority contract.**

## Failure / trigger / consequence

A client can successfully claim and be manually approved, then fail its first local activation. The canonical updater timer is correctly disabled until a healthy first activation, and normal backend deployments correctly require a fresh online Status runtime. Those two rules previously formed a deadlock: an approved pending client with no active release could not receive a newer approved repair release through the canonical deployment chain.

## Root cause

The deployment API had only one current-version authority: online Status presence. The stable updater/download plane existed before activation, but there was no explicit backend authorization mode and no persistent local entrypoint that was permitted to use that plane while `active_release_id` remained `None`.

## Closure

- Normal deployment behavior is unchanged and still requires a fresh online Status version.
- `pre_first_activation_repair` is an explicit superadmin-only deployment mode.
- Backend current baseline comes from the exact server-side fresh-install claim binding recorded by the `client_enrolled` audit in the consuming claim transaction.
- Repair is allowed only when the client is approved, canonical Status is not online, the target is strictly newer than the claim baseline, and an operator reason is present.
- No new artifact store, release selector or approval authority is introduced; target bytes still come from the approved catalog / canonical artifact authority.
- The persistent stable updater PYZ exposes one explicit root-only `repair-first-activation` operation while its timer remains disabled.
- Local repair requires `pending_manual_activation`, no active release/symlink, no activation intent, and an exact provenance match between the original local staged release and the immutable fresh-install binding.
- The existing updater downloads and verifies the exact authorized bundle; the existing privileged controller stages and activates it.
- First activation still re-proves backend client approval through the existing canonical approval gate.
- A repaired first activation preserves the original claim binding, records the newer first active release, and performs normal first-activation cleanup/timer opening.

## Frozen risk

Livestream, Terminal and Remote Desktop are not modified. The shared release/update controller is changed only by adding a pre-first-activation entry path; the ordinary active-release update state machine and its frozen domain agents are not changed.

## Required regressions

1. Offline/no-active pending baseline accepts only explicit repair mode.
2. Online Status rejects repair mode.
3. Missing/invalid server-side claim binding rejects repair.
4. Same/older release rejects repair.
5. Local active release, changed staged baseline or activation intent rejects repair before update mutation.
6. Exact newer deployment uses existing updater/controller and retains first-activation approval proof.
7. Successful repaired first activation keeps original fresh-install binding and records the newer active release.
8. Normal deployment/update tests remain green.
