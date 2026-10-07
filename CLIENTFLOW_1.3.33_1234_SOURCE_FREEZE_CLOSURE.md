# ClientFlow 1.3.33 / sequence 1234 — physical-acceptance failure closure source freeze

## Scope

This is the new immutable source-freeze gate after promoted ClientFlow
1.3.32/1233 failed clean Ubuntu 26.04 physical fresh-install acceptance.

The complete repair set is already merged to canonical `main`. The fresh
repository archive supplied on 2026-10-07 is the only file source used for this
freeze, and its canonical pre-freeze main basis is
`923a4e880ffc96af981cbc5799e57afb0806deab`. The user reports canonical GitHub
CI green for that merged repair source.

The uploaded archive contains no `.git` metadata. This package therefore does
not manufacture a source-freeze SHA. The exact 40-character source-freeze SHA
becomes authoritative only after this freeze package is merged and canonical
GitHub CI is green on that resulting commit.

## Frozen candidate identity

- `client/VERSION = 1.3.33`;
- `release_sequence = 1234`;
- candidate release id: `clientflow-1.3.33-seq-1234`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- embedded runtime Python: `3.13.14`;
- backend/CI Python: `3.13.16`;
- HLS.js release pin: `1.6.16`.

## Catalog boundary

This freeze does not publish or promote 1.3.33/1234. The deployment catalog
remains on the existing immutable selector:

- catalog sequence `1233`;
- latest/default version `1.3.32`;
- selected release `clientflow-1.3.32-seq-1233`;
- `install_modes=["fresh_install"]`;
- `update_allowed=false`;
- rollback remains disabled.

Source/build sequence 1234 therefore leads catalog sequence 1233 by exactly one.
No catalog field is changed by this freeze package. The failed 1.3.32/1233
approved bytes and publication evidence remain immutable.

## Physical failures carried into this freeze

The 1.3.32/1233 physical run proved that 01 provisioning, exact-release
download/integrity, consuming backend claim, durable
`pending_manual_activation`, preactivation reboot, kiosk autologin and local
awaiting-approval GUI all worked. It then exposed later release blockers:

1. **Factory/preactivation NetworkManager/Polkit prompt** — kiosk login could
   automatically present a privileged network-settings authentication dialog.
2. **First-activation health sequencing** — after backend approval, activation
   started but repeatedly failed because
   `clientflow-post-final-reboot-acceptance.service` was checked as active before
   customer handoff/final reboot. The transaction rolled back and retried, which
   left the local GUI at `Approved / Aktiverer` and update status `Aktiverer`.
3. **GNOME kiosk-lockdown dconf convergence** — lockdown commands were rejected
   because the kiosk dconf store below `/run/user/<uid>` was read-only inside the
   hardened systemd sandbox.
4. **Clock projection regression** — Control Room again displayed about 30.4 s
   drift even though NTP was synchronized and the client/backend HTTP clocks
   matched to the second. Ephemeral presence heartbeats had advanced
   `reported_at` independently of the durable status sample.
5. **Browser control acceptance remains open** — Start/Stop kiosk-browser did
   not behave correctly while activation was cycling. Because that observation
   occurred inside the broken activation state, the command path must be
   physically retested after the fundamental activation/lockdown repair rather
   than being claimed fixed from source inspection.

## Frozen correction

The merged source now freezes these behaviours:

- the temporary factory NetworkManager/Polkit guard denies only kiosk-originated
  NetworkManager mutation actions with `polkit.Result.NO`, preventing password
  UI while preserving privileged/root customer activation networking;
- the guard is present before first kiosk login and is retired only after the
  full runtime kiosk-lockdown has been established;
- activation health excludes only units carrying the explicit
  `# ClientFlow-Activation-Health: optional` marker; the post-final-reboot
  acceptance service carries that marker because it is a later handoff gate,
  not a pre-reboot activation-health dependency;
- post-final-reboot acceptance remains condition-gated on durable customer
  handoff and therefore remains mandatory at its correct lifecycle point;
- kiosk UID is rendered into the managed systemd definitions and the hardened
  display/lockdown services receive a narrowly scoped writable
  `/run/user/<uid>` path for GNOME/dconf rather than disabling the broader
  sandbox;
- presence state separates durable `status_reported_at` from ephemeral live
  presence time, and clock drift uses the durable server timestamp paired with
  the same `client_time_utc` sample;
- legacy/readiness snapshot shapes without `status_reported_at` remain
  compatible through a `reported_at` fallback, preserving the Legacy 1.1.19
  capability gate instead of weakening it.

## Preserved boundaries

This source freeze changes release identity/evidence/tests/checksums only; the
runtime repair source was already merged before this branch. In particular:

- embedded Python remains `3.13.14`;
- backend/CI Python remains `3.13.16`;
- HLS.js remains pinned at `1.6.16`;
- database/schema authority is unchanged;
- the five display/browser timing contracts remain exactly 10 seconds;
- authentic in-place update remains unverified and update authority stays closed;
- the ordinary realtime idle polling budget is not shortened;
- kiosk remains non-admin and `cfadmin` remains the local administrator;
- the systemd sandbox is narrowed only by the specific kiosk dconf runtime path;
- immutable 1.3.32/1233 approved/published bytes and evidence are not rewritten.

## Freeze decision

**PASS for source freeze**, subject to canonical GitHub CI on the exact merged
freeze commit.

After that green commit, the release chain is strictly:

1. record the exact 40-character source-freeze SHA;
2. produce source-SHA-qualified sequence-1234 runtime inputs;
3. build two byte-identical 1.3.33/1234 release candidates;
4. manually approve only the exact reproducible candidate bytes, binding
   candidate SHA-256, embedded fresh-installer SHA-256 and source commit;
5. publish the exact approved bytes immutably and independently re-read/verify
   size and whole-bundle SHA-256;
6. promote the catalog separately to 1.3.33/1234 and redeploy the backend;
7. manufacture and byte-verify a new canonical USB from the promoted source;
8. start again from a clean Ubuntu 26.04 baseline and physically execute
   01 -> first kiosk login -> 02 -> preactivation reboot -> backend approval ->
   automatic activation -> converged kiosk lockdown -> final reboot ->
   post-final-reboot acceptance;
9. explicitly retest the NetworkManager password-popup absence, stable approved
   state, local GUI transition, zero/credible clock drift, frontend Start/Stop
   kiosk-browser commands, Control Room live state, Livestream,
   Remote Desktop, Browser Guard, Terminal and all five 10-second contracts;
10. claim physical acceptance only after that promoted end-to-end run passes.
    Any new release-blocking physical failure requires another immutable
    source/build identity.

No physical acceptance, immutable publication or catalog promotion is claimed by
this source-freeze package.
