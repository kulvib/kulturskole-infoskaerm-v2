# ClientFlow 1.3.33 / sequence 1234 — source-frozen identity

Status: source-frozen candidate; not built, physically accepted, published or catalog-promoted.

- Source version: `1.3.33`
- Release sequence: `1234`
- Candidate release id: `clientflow-1.3.33-seq-1234`
- Embedded runtime Python: `3.13.14`
- Backend/CI Python: `3.13.16`
- Minimum Ubuntu LTS: `26.04`
- Architecture: `amd64`
- HLS.js release pin: `1.6.16`
- Pre-freeze merged main basis containing the complete 1.3.32 physical-acceptance repair set:
  `923a4e880ffc96af981cbc5799e57afb0806deab`.
- Promoted catalog remains unchanged at `1.3.32 / 1233`.
- Catalog 1.3.32 remains `fresh_install` only with `update_allowed=false`.
- No in-place update capability is claimed by this source identity.
- No source-freeze commit SHA is inferred from archive contents; the exact freeze SHA
  must be recorded from canonical Git after this freeze package is merged and GitHub CI is green.

## Reason for the new immutable identity

The approved, immutably published and catalog-promoted 1.3.32/1233 bytes failed
the clean Ubuntu 26.04 physical fresh-install acceptance. Those bytes are
therefore historical evidence and must not be rewritten.

The physical run exposed four release-blocking implementation defects:

1. the factory/preactivation kiosk session could trigger a NetworkManager/Polkit
   password prompt because kiosk network mutation had not yet been explicitly
   denied without authentication UI;
2. first activation treated the conditional
   `clientflow-post-final-reboot-acceptance.service` as a pre-reboot activation
   health dependency, causing repeated activation rollback while the required
   customer-handoff state did not yet exist;
3. GNOME kiosk-lockdown could not converge because the systemd sandbox made the
   kiosk user's `/run/user/<uid>` dconf runtime store read-only;
4. ephemeral presence heartbeats advanced the general presence timestamp while
   the durable status sample's `client_time_utc` remained unchanged, recreating
   a false roughly 30-second clock-drift value.

The merged repair keeps those boundaries fail-closed:

- the temporary factory Polkit guard returns `NO` only for NetworkManager actions
  initiated by `clientflow-kiosk`, suppressing an authentication dialog without
  granting network authority;
- post-final-reboot acceptance carries an explicit activation-health optional
  marker and remains a mandatory later post-reboot/customer-handoff gate;
- systemd continues to use the restrictive sandbox while opening only the
  resolved kiosk runtime dconf path that GNOME requires;
- clock drift is projected against `status_reported_at`, the server timestamp
  belonging to the same durable status sample, with a legacy `reported_at`
  fallback retained for older snapshot shapes.

The observed frontend Start/Stop kiosk-browser failure occurred while first
activation was repeatedly rolling back. It is not claimed fixed by source
inspection alone and remains an explicit physical retest item for 1.3.33/1234.

## Release boundary

This identity allocates new immutable release authority for the complete
physical-acceptance repair set. It does not rewrite, replace or republish the
approved 1.3.32/1233 artifact and it does not alter the existing 1.3.32/1233
catalog selector during source freeze.

The runtime catalog must remain on 1.3.32/1233 until the exact 1.3.33/1234
source commit has crossed canonical CI, source-qualified runtime-input transport,
reproducible build, manual approval, immutable publication and independent
store re-read verification.
