# ClientFlow 1.3.24 / sequence 1225 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the
Ubuntu 26.04 factory-handoff defect closure was merged to canonical `main`.

Canonical base before this identity transition:

- main commit: `91b82d6517ee9eafc0d5097fc872065793b687e4`;
- canonical push CI: `#775` / run `35510501782` / completed success;
- source identity: `1.3.23 / 1224`;
- runtime catalog: `clientflow-1.3.23-seq-1224`;
- immutable 1.3.23/1224 status: approved, published and promoted, but canonical
  physical Ubuntu 26.04 fresh-install **FAIL** during factory handoff.

Staged source/build identity after this change:

- version: `1.3.24`;
- release sequence: `1225`;
- candidate release id: `clientflow-1.3.24-seq-1225`.

This document is source/build identity only. It is not approval, publication,
or catalog-promotion authority.

## Included source closures

The 1.3.24/1225 source carries the already merged Ubuntu 26.04 factory-handoff
repairs that are not present in immutable 1.3.23/1224 bytes:

- **CF-1224-SUDO-RS-01:** temporary customer-activation sudoers no longer uses
  classic sudo digest syntax unsupported by Ubuntu 26.04 `sudo-rs`; the
  capability remains exact absolute helper path, no-arguments-only, root-owned,
  non-writable by group/other and validated by the host `visudo` before use;
- **CF-1224-NETPLAN-CLEANUP-02:** factory shipping-network cleanup now removes
  both current NetworkManager profiles and the persistent Netplan network
  subtrees that could regenerate them, runs Netplan generation and revalidates
  the resulting NetworkManager state before `handoff_ready=true`;
- **CF-1224-SYSTEMD-INHIBITOR-HARDENING-03:** controlled reboot authorities use
  systemd 259's documented `--check-inhibitors=no` spelling rather than the
  deprecated/hidden `--ignore-inhibitors` spelling.

The physical 1.3.23/1224 release remains historical FAIL evidence and is not
mutated or reissued.

Livestream, Terminal and Remote Desktop implementation domains remain frozen.

## Release-gate separation

The runtime catalog intentionally remains at the last immutably published and
promoted selector authority:

- `catalog_sequence = 1224`;
- `latest_stable = 1.3.23`;
- `default_install_version = 1.3.23`;
- selected release = `clientflow-1.3.23-seq-1224`.

The source/build identity therefore leads the catalog by exactly one sequence.
The catalog must not select 1.3.24/1225 until the exact candidate has passed
runtime-input transport verification, reproducible build, Ubuntu 26.04
executable-candidate verification, manual approval, immutable publication and
independent store re-read.

## Next gates

After this source-freeze change is merged and its canonical push CI is green:

1. record the exact resulting 40-character source-freeze commit SHA;
2. prepare/verify the locked runtime-input transport for sequence 1225;
3. run the canonical reproducible release build for that exact source SHA and
   runtime input and require byte-identical independent outputs;
4. require the Ubuntu 26.04 executable-candidate gate to pass;
5. manually approve the exact reproducible candidate;
6. publish the approved bytes immutably and independently re-read size/SHA-256;
7. only then promote the separate runtime catalog to 1.3.24/1225;
8. regenerate the canonical preparation USB from promoted main;
9. restart clean Ubuntu 26.04 physical fresh-install acceptance from phase 0.
