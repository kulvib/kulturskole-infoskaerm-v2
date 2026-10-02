# ClientFlow 1.3.29 / sequence 1230 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the
post-promotion physical fresh-install acceptance on Ubuntu 26.04 exposed three
runtime defects in the promoted 1.3.28/1229 release and the corresponding fixes
were merged to canonical `main` with green CI.

Canonical authority before this identity transition:

- source/build identity: `1.3.28 / 1229`;
- runtime catalog: `clientflow-1.3.28-seq-1229`;
- catalog sequence: `1229`;
- database migration head: `20260929_58a_maintenance`;
- minimum Ubuntu LTS: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`.

The exact Git commit SHA of the uploaded fresh-main archive is not embedded in
the archive itself. The authoritative 40-character source-freeze SHA must be
recorded from GitHub after this identity transition is merged and canonical
push CI is green.

Staged source/build identity after this change:

- version: `1.3.29`;
- release sequence: `1230`;
- candidate release id: `clientflow-1.3.29-seq-1230`.

This document is source/build identity only. It is not approval, publication,
or catalog-promotion authority.

## Included physical-acceptance fixes

The staged source contains the already merged fixes proven necessary during the
1.3.28/1229 physical acceptance on Viborg3/Vejle2:

- Remote Desktop no longer attempts to take ownership of the externally owned
  `/home/clientflow-kiosk` root by changing its permissions to `0700`; the
  agent validates the kiosk-home root and keeps its private staging area under
  its own least-privilege directory instead;
- Browser Guard now completes cookie/consent handling on ordinary canonical
  browser starts as well as periodic refresh, so GUI start, backend start,
  boot/start, URL changes and browser reset cannot leave a known consent
  overlay visible after acceptance;
- the local GUI clears all previous calendar status CSS classes during the
  pending-to-approved live transition, restoring the intended green `On` and
  red `Off` calendar colouring.

The earlier post-reboot approval-lifecycle correction is retained. During the
same physical run the client moved from pending readiness to backend approval
and automatic activation without manual refresh, reboot or service restart.

## Runtime Python boundary

The embedded runtime remains Python `3.13.14` in 1.3.29/1230. Although the
promoted 1.3.28/1229 release contains the patch-compatible bridge logic, the
required physical compatibility-bridge update proof from an authentic older
baseline has not been completed. This source identity therefore does not
consume the prepared Python 3.13.15 runtime candidate and does not change the
runtime-platform lock or release-build toolchain.

## Release-gate separation

The runtime catalog deliberately remains on the last approved, published and
promoted selector authority:

- `catalog_sequence = 1229`;
- `latest_stable = 1.3.28`;
- `default_install_version = 1.3.28`;
- selected release = `clientflow-1.3.28-seq-1229`.

The source/build identity therefore leads the catalog by exactly one sequence.
The catalog must not select 1.3.29/1230 until the exact candidate has passed
runtime-input transport verification, reproducible build, Ubuntu 26.04
physical acceptance, manual approval, immutable publication and independent
store re-read.

## Next gates

After this source-freeze change is merged and canonical push CI is green:

1. record the exact resulting 40-character source-freeze commit SHA;
2. build the deterministic source-SHA-qualified runtime-input transport for sequence 1230 using the still-pinned Python 3.13.14 platform inputs;
3. run the canonical reproducible release build for that exact source SHA;
4. require byte-identical independent candidate outputs and the Ubuntu 26.04 executable-candidate gate;
5. physically verify the exact 1.3.29/1230 candidate, including Remote Desktop connection/file access, Browser Guard across canonical start/reset/config-change paths, calendar colours, and the 1.3.28 -> 1.3.29 in-place update path;
6. only after physical candidate acceptance, manually approve the exact reproducible candidate;
7. publish the approved bytes immutably and independently re-read size/SHA-256;
8. only then promote the runtime catalog to 1.3.29/1230;
9. regenerate the canonical preparation USB from promoted main and repeat final clean-install release acceptance.
