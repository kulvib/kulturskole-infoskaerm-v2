# ClientFlow 1.3.32 / sequence 1233 — physical-acceptance runtime convergence source freeze

## Scope

This is the new source-freeze gate after clean Ubuntu 26.04 physical acceptance
of promoted ClientFlow 1.3.31/1232 exposed release-blocking runtime/convergence
failures after the pre-activation sequencing repair itself had worked. The
complete acceptance-fix set is already merged to canonical `main`; the fresh
archive supplied on 2026-10-06 is the only source used for this freeze, and the
pre-freeze merged main basis is
`7623c972ab5e0db7ee2a9da31023ee1e067e7d97`. GitHub CI for that merged repair
source is reported green.

The uploaded archive contains no `.git` metadata. This package therefore does
not guess or manufacture the resulting source-freeze commit SHA. The exact
40-character source-freeze SHA becomes authoritative only after this freeze
package is merged and canonical GitHub CI is green on that resulting commit.

## Frozen candidate identity

- `client/VERSION = 1.3.32`;
- `release_sequence = 1233`;
- candidate release id: `clientflow-1.3.32-seq-1233`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- embedded runtime Python: `3.13.14`;
- backend/CI Python: `3.13.16`;
- HLS.js release pin: `1.6.16`.

## Catalog boundary

This freeze does not publish or promote 1.3.32/1233. The deployment catalog
remains on the last immutable published selector:

- catalog sequence `1232`;
- latest/default version `1.3.31`;
- selected release `clientflow-1.3.31-seq-1232`;
- `install_modes=["fresh_install"]`;
- `update_allowed=false`;
- rollback remains disabled.

Source/build sequence 1233 therefore leads catalog sequence 1232 by exactly one.
No catalog field is changed by this freeze package.

## Physical failure carried into the freeze

The 1.3.31/1232 physical run proved that the repaired 02 flow correctly reached
durable `pending_manual_activation`, performed the required pre-activation
reboot, displayed the preactivation state and allowed automatic first activation
after backend approval. It then exposed later acceptance failures rather than the
previous 1.3.30 sequencing defect.

The observed release blockers were:

1. **Clock integrity projection** — the UI could report roughly status-age-sized
   clock drift because client time was compared with read time rather than the
   server timestamp from the same status sample.
2. **Kiosk-lockdown boot convergence** — final acceptance could run before four
   GNOME lockdown settings had converged in the active kiosk Wayland/D-Bus
   session, leaving lockdown fail-closed instead of automatically reasserting the
   intended always-on baseline once the session was ready.
3. **First-activation status transition** — the already visible local GUI could
   transiently show backend `pending` and `ClientFlow update: unknown` while the
   approved handoff was still committing.
4. **Control Room live status** — a realtime wake arriving around an in-flight
   snapshot/capability transition could be consumed without forcing the required
   follow-up snapshot, delaying visible status until fallback polling.
5. **Frontend session resilience** — transient refresh/network failures could be
   treated like authoritative authentication rejection and log the operator out;
   Livestream heartbeat/control traffic also needed the shared refresh-aware
   authentication path.
6. **Livestream operational UX/recovery** — the overview required explicit
   fullscreen support, visible stream delay in seconds and stable recovery around
   signal-timeout conditions.

## Frozen correction

The merged source now freezes these behaviours:

- clock drift is derived from one coherent client/server status sample rather
  than from the age of a durable status row;
- post-final-reboot acceptance can reassert the GNOME lockdown baseline only
  after the canonical local seat0 Wayland session and user D-Bus are verified,
  and still fails closed if the baseline cannot be proven;
- the local GUI represents the approved first-activation transition explicitly
  instead of presenting stale pending/update-unknown values as steady state;
- realtime wakeups that occur during an in-flight status request force a
  subsequent snapshot, while the normal 60-second idle polling budget remains
  unchanged;
- only authoritative authentication rejection ends the frontend session;
  transient refresh transport failures preserve the session for retry, refresh
  remains serialized, and refresh-token rotation/replay protection is retained;
- Livestream viewer/control traffic uses the common refresh-aware auth path;
- Livestream Overview exposes fullscreen and measured playback delay and keeps
  timeout recovery inside the existing bounded control-plane behaviour.

Regression contracts cover these repair paths without weakening existing
security, liveness, cost or post-final-reboot gates.

## Preserved boundaries

This source freeze changes release identity/evidence only; the acceptance fixes
were already merged before the freeze branch. In particular:

- embedded Python remains `3.13.14`;
- backend/CI Python remains `3.13.16`;
- HLS.js remains pinned at `1.6.16`;
- database/schema authority is unchanged;
- the five display/browser timing contracts remain exactly 10 seconds;
- update authority remains closed because authentic physical in-place update is
  still unverified;
- the ordinary realtime idle poll is not shortened to conceal wakeup bugs;
- refresh-token rotation/replay protection is not weakened;
- immutable 1.3.31/1232 approved/published bytes and evidence are not rewritten.

## Freeze decision

**PASS for source freeze**, subject to canonical GitHub CI on the exact merged
freeze commit.

After that green commit, the release chain is strictly:

1. record the exact 40-character source-freeze SHA;
2. produce source-SHA-qualified sequence-1233 runtime inputs;
3. build two byte-identical 1.3.32/1233 release candidates;
4. manually approve only the exact reproducible candidate bytes, binding the
   candidate SHA-256, embedded fresh-installer SHA-256 and source commit;
5. publish the exact approved bytes immutably and independently re-read/verify
   size and SHA-256;
6. promote the catalog separately to 1.3.32/1233 and redeploy the backend;
7. manufacture and verify a new canonical USB from that promoted source;
8. physically test the exact promoted approved bytes from a clean Ubuntu 26.04
   baseline through 01 -> 02 -> pre-activation reboot -> backend approval and
   automatic activation -> converged kiosk lockdown -> final reboot ->
   post-final-reboot acceptance;
9. rerun the relevant frozen-domain regression set, including clock integrity,
   client-list realtime status, frontend session longevity, Livestream delay /
   fullscreen / timeout recovery, Remote Desktop, Browser Guard, all five
   10-second display/browser contracts, service health, Terminal and local GUI;
10. claim physical acceptance only after the promoted end-to-end test passes.
    A failure remains a release acceptance failure and requires another new
    source/build identity; approved/published bytes are never rewritten in place.

No physical acceptance, immutable publication or catalog promotion is claimed
by this source-freeze closure itself.
