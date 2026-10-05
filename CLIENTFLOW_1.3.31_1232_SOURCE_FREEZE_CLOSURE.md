# ClientFlow 1.3.31 / sequence 1232 — pre-activation reboot sequencing source freeze

## Scope

This is the source-freeze gate after clean Ubuntu 26.04 physical acceptance of
promoted ClientFlow 1.3.30/1231 exposed a release-blocking sequencing defect in
`02 Aktiver ClientFlow`. The complete correction is already merged to the fresh
canonical `main` archive supplied on 2026-10-05 and GitHub CI is reported green
for that merged source.

The uploaded archive contains no `.git` metadata, so this package does not
guess, manufacture or self-embed the exact canonical commit SHA. That
40-character source-freeze SHA becomes authoritative only after this freeze
package is merged and canonical GitHub CI is green on the resulting commit.

## Frozen candidate identity

- `client/VERSION = 1.3.31`;
- `release_sequence = 1232`;
- candidate release id: `clientflow-1.3.31-seq-1232`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- embedded runtime Python: `3.13.14`;
- backend/CI Python: `3.13.16`;
- HLS.js release pin: `1.6.16`.

## Catalog boundary

This freeze does not publish or promote 1.3.31/1232. The deployment catalog
remains on the last immutable published selector:

- catalog sequence `1231`;
- latest/default version `1.3.30`;
- selected release `clientflow-1.3.30-seq-1231`;
- `install_modes=["fresh_install"]`;
- `update_allowed=false`;
- rollback remains disabled.

Source/build sequence 1232 therefore leads catalog sequence 1231 by exactly one.
No catalog field is changed by this freeze package.

## Physical failure carried into the freeze

The 1.3.30/1231 run proved the preparation path through USB integrity, factory
handoff, kiosk autologin, customer network selection, invalid CF-code retry,
exact approved release download and integrity, backend claim and durable
`pending_manual_activation` state.

The blocking failure was then captured with root-readable evidence:

- install state remained `pending_manual_activation`;
- `active_release_id` remained unset;
- `preclaim_boot_id` equalled the current boot id;
- `/run/reboot-required` existed;
- the staged 1.3.30/1231 kiosk-lockdown helper existed and was executable;
- `/opt/clientflow/active` was absent;
- the first-activation waiter and preactivation GUI units were enabled but
  inactive and had no activation journal entries.

That proves the helper was not missing from the release. The defect was that the
outer customer flow attempted active-release-only lockdown before the required
pre-activation reboot and canonical activation had occurred.

## Frozen correction

The frozen source now preserves the lifecycle boundary already described by the
canonical release procedure:

1. durable `pending_manual_activation` is required before bootstrap activation
   rights and desktop launcher are removed;
2. the kiosk graphical-session baseline and preactivation GUI unit are staged;
3. the first-activation approval waiter is installed/enabled;
4. the operator explicitly confirms the controlled pre-activation reboot;
5. `02 Aktiver ClientFlow` returns after queueing that reboot and performs no
   active-release-only work in the same boot;
6. after reboot, canonical kiosk Wayland + visible preactivation GUI readiness
   is published before backend approval/activation may complete;
7. successful canonical activation creates the active release;
8. only then is kiosk lockdown applied and verified;
9. the final controlled reboot is staged and post-final-reboot acceptance must
   pass fail-closed before customer handoff is accepted.

Regression contracts cover the pre-activation reboot ordering, resume/crash
paths and the prohibition against phase-8 lockdown before an active release.

## Preserved boundaries

This repair freeze does not combine unrelated changes:

- embedded Python remains `3.13.14`;
- backend/CI Python remains `3.13.16`;
- HLS.js remains pinned at `1.6.16`;
- database/schema authority is unchanged;
- the five display/browser timing contracts remain exactly 10 seconds;
- update authority remains closed because authentic physical in-place update is
  still unverified;
- immutable 1.3.30/1231 release bytes and approval evidence are not rewritten.

## Freeze decision

**PASS for source freeze**, subject to canonical GitHub CI on the exact merged
freeze commit.

After that green commit, the release chain is strictly:

1. record the exact 40-character source-freeze SHA;
2. produce source-SHA-qualified sequence-1232 runtime inputs;
3. build two byte-identical 1.3.31/1232 release candidates;
4. manually approve only the exact reproducible candidate bytes, binding the
   candidate SHA-256, embedded fresh-installer SHA-256 and source commit;
5. publish the exact approved bytes immutably and independently re-read/verify
   size and SHA-256;
6. promote the catalog separately to 1.3.31/1232 and redeploy the backend;
7. physically test the exact promoted approved bytes from a fresh clean Ubuntu
   26.04 baseline through the canonical USB/operator path, including
   pre-activation reboot, backend approval/activation, kiosk lockdown, final
   reboot and post-final-reboot acceptance;
8. claim physical acceptance only after that promoted end-to-end test passes.
   A failure remains a release acceptance failure and requires a new source/build
   identity; approved/published bytes are never rewritten in place.

No physical acceptance, immutable publication or catalog promotion is claimed
by this source-freeze closure itself.
