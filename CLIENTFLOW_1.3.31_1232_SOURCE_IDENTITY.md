# ClientFlow 1.3.31 / sequence 1232 — source-frozen identity

Status: source-frozen candidate; not built, physically accepted, published or catalog-promoted.

- Source version: `1.3.31`
- Release sequence: `1232`
- Candidate release id: `clientflow-1.3.31-seq-1232`
- Embedded runtime Python: `3.13.14`
- Backend/CI Python: `3.13.16`
- Minimum Ubuntu LTS: `26.04`
- Architecture: `amd64`
- HLS.js release pin: `1.6.16`
- Promoted catalog remains immutable at `1.3.30 / 1231`.
- Catalog 1.3.30 remains `fresh_install` only with `update_allowed=false` until a later explicit selector change.
- No in-place update capability is claimed by this source identity.
- No source commit SHA is inferred from archive contents; the exact freeze SHA
  must be recorded from canonical Git after merge and green GitHub CI.

## Reason for the new immutable identity

The promoted 1.3.30/1231 physical fresh-install acceptance failed after the
canonical installer had durably committed `pending_manual_activation`. The
physical failure state proved all of the following at the same time:

- `preclaim_boot_id` still matched the current boot and Ubuntu reported a
  reboot requirement;
- `clientflow-first-activation.service` was enabled but inactive and had not
  yet executed;
- the exact 1.3.30/1231 release was staged and its
  `runtime/bin/clientflow-kiosk-lockdown` helper existed;
- `/opt/clientflow/active` did not yet exist because canonical activation had
  not happened;
- the outer customer activation flow nevertheless advanced immediately to
  active-release-only kiosk lockdown and failed.

The merged correction makes the intended lifecycle explicit and fail-closed:
phase 7 installs/enables the preactivation GUI and first-activation waiter,
requires the operator-confirmed controlled pre-activation reboot, and returns
without attempting active-release-only work in the same boot. After the new
boot, canonical kiosk Wayland readiness and backend approval drive automatic
activation. Only after the release is active may phase 8 apply/verify kiosk
lockdown; phase 9 then performs the controlled final reboot and post-final-
reboot acceptance.

## Release boundary

This identity allocates new immutable release authority for the merged fix. It
does not rewrite, replace or republish the approved 1.3.30/1231 bytes and does
not retroactively alter their physical-acceptance result.

The runtime catalog deliberately remains on 1.3.30/1231 while 1.3.31/1232 is
only a source/build candidate. No new fresh-install use of 1.3.30/1231 should
be used as acceptance evidence after the documented failure; selector authority
must move only after the 1.3.31/1232 candidate crosses the full release chain.
