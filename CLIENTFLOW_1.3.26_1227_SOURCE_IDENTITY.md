# ClientFlow 1.3.26 / sequence 1227 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the
post-1226 parity, readiness, kiosk-hardening, update-safety and Control Room
configuration work was merged to canonical `main`.

Canonical authority before this identity transition:

- source/build identity: `1.3.25 / 1226`;
- runtime catalog: `clientflow-1.3.25-seq-1226`;
- catalog sequence: `1226`;
- database migration head: `20260922_56a_calendar_rev`;
- minimum Ubuntu LTS: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`.

The exact Git commit SHA of the uploaded fresh-main archive is not embedded in
the archive itself. The authoritative 40-character source-freeze SHA must be
recorded from GitHub after this identity transition is merged and canonical
push CI is green.

Staged source/build identity after this change:

- version: `1.3.26`;
- release sequence: `1227`;
- candidate release id: `clientflow-1.3.26-seq-1227`.

This document is source/build identity only. It is not approval, publication,
or catalog-promotion authority.

## Included post-1226 closures

The 1.3.26/1227 source includes the merged work completed while the release was
intentionally paused, including:

- factory post-reboot readiness and conservative Ubuntu package-health proof;
- Terminal Enter/admin UX and canonical read-only support diagnostics;
- Remote Desktop kiosk-home file parity with least-privilege confinement;
- local GUI legacy-status/layout parity and canonical event-source state;
- Control Room configuration split into domain-scoped actions instead of one
  mixed transaction;
- kiosk-lockdown observed-state verification, drift detection and reconciliation;
- non-removing runtime Ubuntu update with APT lock waiting and package-health gate;
- permanent kiosk notification suppression for GNOME/system banners;
- permanent kiosk command-line baseline while preserving ClientFlow local GUI,
  activation GUI and controlled Terminal services;
- repo/database-performance audit closure with no speculative performance change
  opened without runtime evidence.

Livestream remains outside these packages except where an existing status or
support surface reads it without changing Livestream authority or runtime logic.

## Release-gate separation

The runtime catalog deliberately remains on the last approved, published and
promoted selector authority:

- `catalog_sequence = 1226`;
- `latest_stable = 1.3.25`;
- `default_install_version = 1.3.25`;
- selected release = `clientflow-1.3.25-seq-1226`.

The source/build identity therefore leads the catalog by exactly one sequence.
The catalog must not select 1.3.26/1227 until the exact candidate has passed
runtime-input transport verification, reproducible build, Ubuntu 26.04
candidate/physical acceptance gates, manual approval, immutable publication and
independent store re-read.

## Next gates

After this source-freeze change is merged and canonical push CI is green:

1. record the exact resulting 40-character source-freeze commit SHA;
2. prepare/verify the locked runtime-input transport for sequence 1227;
3. run the canonical reproducible release build for that exact source SHA;
4. require byte-identical independent candidate outputs and executable-candidate PASS;
5. stage the exact candidate for physical Ubuntu 26.04 clean-install acceptance;
6. after physical acceptance, manually approve the exact reproducible candidate;
7. publish approved bytes immutably and independently re-read size/SHA-256;
8. only then promote the runtime catalog to 1.3.26/1227;
9. regenerate the canonical preparation USB from promoted main and run final release acceptance.
