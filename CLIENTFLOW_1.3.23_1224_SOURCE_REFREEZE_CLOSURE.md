# ClientFlow 1.3.23 / sequence 1224 — source re-freeze closure

Date: 2026-09-19

## Status

This document supersedes the **initial source-freeze boundary** described in
`CLIENTFLOW_1.3.23_1224_SOURCE_FREEZE_CLOSURE.md`.

The staged release identity itself remains `1.3.23 / 1224`. The initial freeze
was intentionally stopped before runtime-input transport, reproducible release
build, approval, immutable publication or catalog promotion because additional
performance, database-efficiency and auth-route fixes were merged afterwards.
No 1.3.23/1224 approved artifact was published, and the runtime catalog remains
on the immutable approved 1.3.22/1223 release.

Canonical pre-refreeze main:

- commit: `a7dbbfaea404733d00a0070e62c644cd5460e6eb`;
- canonical push CI: `#758` / run `35449745659` / completed success;
- staged source identity: `1.3.23 / 1224`;
- runtime catalog: `1.3.22 / 1223`.

The exact post-merge re-freeze SHA is deliberately not embedded in this source.
It must be recorded only after this re-freeze package is merged to canonical
`main` and the resulting push CI is green.

## Why the same staged identity is retained

`1.3.23/1224` never crossed an artifact-authority boundary. No sequence-1224
runtime-input transport, candidate approval, immutable publication or catalog
promotion was completed from the initial freeze. Therefore this package does
not create a sequence gap or falsely promote an unbuilt candidate. The source
sequence continues to lead the published catalog by exactly one:

- source release sequence: `1224`;
- catalog sequence: `1223`;
- catalog latest/default: `1.3.22`;
- selected release: `clientflow-1.3.22-seq-1223`.

## Additional closures included since the initial freeze

The re-frozen candidate includes the original factory/customer lifecycle and
pre-activation GUI closures plus the following merged work:

1. **Control-room performance hotpaths**
   - presence status + credential reads consolidated;
   - `/chrome-status` carries canonical presence;
   - redundant presence polling removed;
   - overlapping polling guarded.
2. **Database cost efficiency**
   - shared-agent auth validates credential + parent client in one joined read;
   - idle Display/System command-claim query count reduced;
   - agent command polling aligned to 5 seconds while heartbeat remains 15 seconds;
   - hidden-tab DB polling paused where safe.
3. **Database request budget + observability**
   - request-scoped SQL statement/checkout/cursor-duration metrics;
   - safe `Server-Timing` DB timing on `/api/clients*`;
   - safe Neon/pool topology classification without exposing host or credentials;
   - redundant action-confirmation full-client reads removed.
4. **Shared live-state polling consolidation**
   - ClientFlow deployment state has one parent-owned polling source;
   - idle deployment polling removed;
   - Ubuntu update follows existing `/chrome-status` live state;
   - local-management state is carried by the existing System projection.
5. **Direct browser API transport**
   - ordinary browser API traffic goes directly to `api.display.planiq.dk`;
   - login/refresh/logout remain same-origin to preserve the existing HttpOnly
     refresh-cookie boundary;
   - measured production acceptance reduced median request wall time from
     840.9 ms to 125.4 ms for `/api/clients/` (85.1% improvement) and from
     427.6 ms to 119 ms for `/chrome-status` (72.2% improvement).
6. **Auth route-churn closure**
   - AuthProvider owns session bootstrap once per browser entry;
   - internal navigation no longer causes duplicate DB-backed `/auth/me` reads;
   - ProtectedRoute is a UI/role/password-change gate;
   - backend user/token-version validation and 401 refresh/retry remain authoritative.

Livestream, product Terminal and Remote Desktop implementation domains remain
frozen except for transport plumbing already covered by the direct API closure;
no capability semantics were redesigned by these performance closures.

## Fresh-main audit before re-freeze

The fresh `main` ZIP based on commit
`a7dbbfaea404733d00a0070e62c644cd5460e6eb` was inspected as the sole source of
truth.

PASS:

- direct API transport is present in production configuration;
- no ordinary frontend `fetch("/api/...")` call bypasses the configured direct
  API transport; deliberate same-origin auth endpoints remain documented;
- auth route-churn closure is present;
- `client/VERSION` remains `1.3.23`;
- `client/release/release-input.json` remains sequence `1224`;
- catalog remains `1.3.22 / 1223` and source still leads it by exactly one;
- no new release-blocking product defect was found in the final audit;
- complete `scripts/tests` suite: `251 passed` locally;
- canonical GitHub push CI #758 / run 35449745659 is green on the pre-refreeze baseline.

Large files such as `backend/service1/routers/clients.py` and
`ClientDetailsInfoSection.jsx` remain maintainability candidates, but file size
alone is not a release defect. They are deliberately **not** refactored in this
re-freeze package because a cosmetic split immediately before release would
increase regression surface without fixing a proven release blocker.

## Authority boundary

This re-freeze is source/build authority only. It is not artifact approval,
publication or catalog-promotion authority.

The following are explicitly forbidden until this package is merged and the
new canonical source-freeze SHA has green push CI:

- sequence-1224 runtime-input transport;
- release build for 1.3.23/1224;
- candidate approval;
- immutable publication;
- catalog promotion to 1.3.23/1224;
- preparation-USB regeneration for 1.3.23/1224.

## Next canonical gates

After merge and green canonical push CI:

1. record the exact resulting 40-character **re-freeze source SHA**;
2. prepare/verify the locked runtime-input transport for sequence 1224 from
   that exact source authority;
3. dispatch the canonical reproducible release build for that exact source SHA
   and locked runtime input;
4. require byte-identical independent candidate outputs and the Ubuntu 26.04
   executable-candidate gate to pass;
5. manually approve that exact candidate;
6. publish the approved bytes immutably and independently re-read size/SHA-256;
7. separately promote the runtime catalog to 1.3.23/1224;
8. regenerate the canonical preparation USB from promoted main;
9. restart clean Ubuntu 26.04 physical fresh-install acceptance from phase 0.
