# ClientFlow 1.3.23 / sequence 1224 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the
factory → customer handoff and pre-activation local-GUI closures were merged
to canonical `main`.

Canonical base before this identity transition:

- main commit: `a969a7f046f748243e539f208d3c5e69c5585e72`;
- canonical push CI: `#722` / run `35429313779` / completed success;
- source identity: `1.3.22 / 1223`;
- runtime catalog: `clientflow-1.3.22-seq-1223`;
- immutable 1.3.22/1223 status: approved, published and promoted.

Staged source/build identity after this change:

- version: `1.3.23`;
- release sequence: `1224`;
- candidate release id: `clientflow-1.3.23-seq-1224`.

This document is source/build identity only. It is not approval, publication,
or catalog-promotion authority.

## Included source closures

The 1.3.23/1224 source freezes the already merged factory/customer lifecycle
changes that are not present in immutable 1.3.22/1223 bytes:

- **01 Klient klargøring** now establishes the shipping-ready account/session
  boundary: canonical `clientflow-kiosk` and `cfadmin`, office-side `cfadmin`
  password selection, kiosk Wayland autologin and kiosk-owned **02 Aktiver
  ClientFlow**;
- customer activation uses only the exact SHA-256-bound root-owned activation
  helper through temporary `sudo -n`, with no command arguments and no customer
  sudo-password prompt;
- saved WiFi/Ethernet/GSM/CDMA/VPN/WireGuard NetworkManager profiles are removed
  and rechecked before the shipping reboot;
- the canonical fresh installer accepts those pre-provisioned human accounts
  only when the private schema-2 factory-state is `handoff_ready=true` and the
  account identity/permissions revalidate; unknown legacy traces still fail
  closed;
- customer-facing terminal UX again exposes cable-first diagnostics, explicit
  progress/status lines, release-download byte/percentage progress and ordinary
  package-manager output where host repair is actually required, without
  printing secrets;
- after durable `pending_manual_activation` and customer reboot, the existing
  release-owned GTK4 GUI starts in explicit pre-activation status-only mode,
  retaining the legacy 1.1.19 visual layout while full ClientFlow runtime
  remains approval-gated;
- Start/Stop kiosk remain disabled before approval and no administrator-switch
  action is exposed;
- backend-approved activation stops the temporary pending GUI and starts the
  normal release-owned runtime GUI through `clientflow.target`.

Livestream, Terminal and Remote Desktop implementation domains remain frozen.

## Release-gate separation

The runtime catalog intentionally remains at the last immutably published and
promoted selector authority:

- `catalog_sequence = 1223`;
- `latest_stable = 1.3.22`;
- `default_install_version = 1.3.22`;
- selected release = `clientflow-1.3.22-seq-1223`.

The source/build identity therefore leads the catalog by exactly one sequence.
The catalog must not select 1.3.23/1224 until the exact candidate has passed
reproducible build, Ubuntu 26.04 executable-candidate verification, manual
approval, immutable publication and independent store re-read.

## Next gates

After this source-freeze change is merged and its canonical push CI is green:

1. record the exact resulting 40-character source-freeze commit SHA;
2. prepare/verify the locked runtime-input transport for sequence 1224;
3. run the canonical reproducible release build for that exact source SHA and
   runtime input and require byte-identical independent outputs;
4. require the Ubuntu 26.04 executable-candidate gate to pass;
5. manually approve the exact reproducible candidate;
6. publish the approved bytes immutably and independently re-read size/SHA-256;
7. only then promote the separate runtime catalog to 1.3.23/1224;
8. regenerate the canonical preparation USB from promoted main;
9. restart clean Ubuntu 26.04 physical fresh-install acceptance from the
   beginning.
