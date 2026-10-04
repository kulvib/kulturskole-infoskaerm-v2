# ClientFlow 1.3.30 / sequence 1231 — source freeze closure

## Scope

This is the source-freeze gate for ClientFlow 1.3.30 / sequence 1231 after the
post-1.3.29 hardening and operator-visibility work was merged and re-audited.
The canonical pre-freeze source is the fresh `main` archive supplied on
2026-10-04. The archive contains no `.git` metadata, so this closure does not
guess, manufacture or self-embed a source commit SHA.

No runtime, UI, database, transport, dependency or catalog selector change is
introduced by this freeze package. It freezes the already-staged source
identity and records the validation/release boundary needed before release
artifact production.

## Frozen source identity

- `client/VERSION = 1.3.30`;
- `release_sequence = 1231`;
- candidate release id: `clientflow-1.3.30-seq-1231`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- embedded runtime Python: `3.13.14`;
- backend/CI Python: `3.13.16`;
- HLS.js release pin: `1.6.16`;
- promoted catalog remains immutable at `1.3.29 / sequence 1230`.

The exact 40-character source-freeze SHA becomes authoritative only after this
freeze package is merged to canonical `main` and GitHub CI is green on that
exact commit.

## Catalog and updater boundary

This freeze does not publish or promote 1.3.30/1231.

The runtime catalog remains:

- catalog sequence `1230`;
- latest/default version `1.3.29`;
- selected release `clientflow-1.3.29-seq-1230`;
- `update_allowed=false`;
- `install_modes=["fresh_install"]`.

Authentic in-place update from an older physical ClientFlow installation is
still unverified. This source freeze therefore does not claim updater physical
acceptance and does not reopen update authority.

## Hardening preserved in the frozen source

The freeze retains the previously audited 1.3.30/1231 hardening without
changing its runtime semantics, including:

- outbound-TCP-443-compatible WSS fast paths with HTTPS fallback for core
  realtime/control paths;
- Neon/Postgres as durable authority while high-frequency wake/presence stays
  outside the database hot path;
- 25-second Livestream viewer heartbeat, 75-second lease and 30-second producer
  stop grace;
- 30-second browser-tab warm grace for Livestream and Remote Desktop;
- shared Livestream producer/generation semantics across simultaneous viewers;
- viewport-bounded superadministrator Livestream overview;
- deterministic operator health issues and role-limited health visibility;
- canonical Control Room list projection reuse without an additional database
  projection/query;
- transactional kiosk lockdown with Nautilus/DING readiness and rollback;
- fail-closed post-final-reboot acceptance;
- exactly 10-second boot/start, URL/config-change, backend/GUI start, reset and
  display-sleep contracts;
- Remote Desktop resource bounds, HTTPS relay fallback and EXDEV-safe file
  publication;
- embedded Python remaining 3.13.14 while backend/CI uses Python 3.13.16;
- HLS.js remaining explicitly pinned at 1.6.16 for this release line.

## Explicitly deferred architecture

The following are deliberately not introduced by this freeze and are not
missing release requirements:

- WebRTC/video codec as the mandatory/default Remote Desktop transport;
- Redis/Valkey as realtime correctness authority;
- Neon Functions migration;
- PostgreSQL `LISTEN/NOTIFY` as the product realtime bus;
- updater push/cost optimization before authentic physical in-place update is
  proven.

Existing optional Redis use for rate limiting is not a realtime authority and
is outside this deferred-architecture boundary.

## Freeze decision

**PASS for source freeze**, subject to canonical GitHub CI on the exact merged
freeze commit.

After that green commit, the release sequence is strictly:

1. record the exact source-freeze SHA;
2. produce source-SHA-qualified sequence-1231 runtime inputs;
3. build reproducible, byte-identical release-candidate bytes;
4. physically test those exact bytes, including final reboot/lockdown and
   customer-network behaviour;
5. record physical acceptance;
6. publish immutably and independently re-read/verify the published bytes;
7. promote the catalog separately and only after the preceding gates pass.

No physical acceptance, immutable publication or catalog promotion is claimed
by this source-freeze closure itself.
