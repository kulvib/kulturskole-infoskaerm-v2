# ClientFlow 1.3.32 / sequence 1233 — source-frozen identity

Status: source-frozen candidate; not built, physically accepted, published or catalog-promoted.

- Source version: `1.3.32`
- Release sequence: `1233`
- Candidate release id: `clientflow-1.3.32-seq-1233`
- Embedded runtime Python: `3.13.14`
- Backend/CI Python: `3.13.16`
- Minimum Ubuntu LTS: `26.04`
- Architecture: `amd64`
- HLS.js release pin: `1.6.16`
- Pre-freeze merged main basis containing the physical-acceptance repairs: `7623c972ab5e0db7ee2a9da31023ee1e067e7d97`.
- Promoted catalog remains immutable at `1.3.31 / 1232`.
- Catalog 1.3.31 remains `fresh_install` only with `update_allowed=false`.
- No in-place update capability is claimed by this source identity.
- No source-freeze commit SHA is inferred from archive contents; the exact freeze SHA
  must be recorded from canonical Git after this freeze package is merged and GitHub CI is green.

## Reason for the new immutable identity

The promoted and immutably published 1.3.31/1232 release passed the corrected
pre-activation reboot sequencing path, but its physical fresh-install acceptance
then exposed additional release-blocking runtime/convergence defects. The physical
run observed all of the following:

- reported clock drift could be inflated by status-sample age instead of measuring
  client clock against the server timestamp for the same report;
- post-activation kiosk-lockdown could reach final reboot before the GNOME
  lockdown baseline had converged, leaving the client pending/fail-closed;
- local activation status could transiently show backend `pending` and
  `ClientFlow update: unknown` during the approved first-activation handoff;
- Control Room realtime status could miss a wake event around snapshot/capability
  setup and therefore fail to update live until fallback polling;
- transient refresh/network failures could log an authenticated frontend session
  out prematurely, while Livestream control/heartbeat traffic did not consistently
  share the refresh-aware auth path;
- Livestream Overview lacked explicit fullscreen and observable stream-delay
  presentation, and physical use exposed signal-timeout handling that needed to
  remain recoverable rather than destabilize the authenticated control surface.

Those issues were corrected on canonical main before this freeze. The merged
repair keeps the security boundaries intact: refresh-token rotation/replay
protection is preserved, realtime idle polling is not shortened to mask missed
wakeups, kiosk lockdown remains fail-closed, and update authority remains closed.

## Release boundary

This identity allocates new immutable release authority for the merged physical-
acceptance repairs. It does not rewrite, replace or republish the approved
1.3.31/1232 bytes and does not retroactively alter their failed physical-
acceptance result.

The runtime catalog deliberately remains on 1.3.31/1232 while 1.3.32/1233 is
only a source/build candidate. Selector authority must move only after the new
candidate crosses the normal exact-source build, approval, immutable publication
and separate catalog-promotion gates.
