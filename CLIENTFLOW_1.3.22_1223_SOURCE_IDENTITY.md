# ClientFlow 1.3.22 / sequence 1223 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the
physical Ubuntu 26.04 acceptance of immutable 1.3.21/1222 exposed
`CF-1222-LAUNCHER-01` in the generated desktop terminal wrapper.

Canonical base before this identity transition:

- main commit: `edb740b5a32055918e36ad0ec28232b4b1ae6ab7`
- source identity: `1.3.21 / 1222`
- runtime catalog: `clientflow-1.3.21-seq-1222`
- immutable 1.3.21/1222 status: approved and published, but canonical physical fresh-install **FAIL** at the first desktop launcher execution
- physical root cause: generated wrapper expanded `$rc` in the outer `set -u` shell before the inner `bash -lc` command ran

Staged source/build identity after this change:

- version: `1.3.22`
- release sequence: `1223`
- candidate release id: `clientflow-1.3.22-seq-1223`

This document is source/build identity only. It is not approval, publication,
or catalog-promotion authority.

## Included source closures

The 1.3.22/1223 source includes the already merged closures that were not part
of the immutable 1.3.21/1222 bytes:

- `CF-1222-LAUNCHER-01`: generated desktop terminal launchers shell-quote the
  complete inner command, defer `$?`/`$rc` evaluation to the inner shell, and
  prefer the explicit Ptyxis `-- PROGRAM ARGS` path on Ubuntu 26.04;
- execution regression coverage for both phase-1 and phase-2 terminal launchers;
- PlanIQ Display desktop-icon branding using the existing repo-owned
  `frontend/public/brand/planiq-display/planiq-display-mark.png` asset;
- deterministic USB payload/checksum coverage for that exact brand asset.

Livestream, Terminal and Remote Desktop implementation domains remain frozen.

## Release-gate separation

The runtime catalog intentionally remains at the last immutably published
selector authority:

- `catalog_sequence = 1222`
- `latest_stable = 1.3.21`
- `default_install_version = 1.3.21`
- selected release = `clientflow-1.3.21-seq-1222`

The source/build identity therefore leads the catalog by exactly one sequence.
The catalog must not select 1.3.22/1223 until the exact 1.3.22/1223 candidate
has passed reproducible build, Ubuntu 26.04 executable-candidate verification,
manual approval, immutable publication, and independent size/SHA-256 re-read.

## Next gates

After this source-freeze change is merged and its canonical push CI is green:

1. record the exact resulting 40-character source-freeze commit SHA externally;
2. prepare/verify the locked runtime-input transport for sequence 1223;
3. run the canonical release build twice for that exact source SHA and runtime input;
4. require byte-identical candidate outputs and Ubuntu 26.04 executable-candidate PASS;
5. manually approve the exact reproducible candidate;
6. publish the approved bytes immutably and independently re-read size/SHA-256;
7. only then promote the separate runtime catalog to 1.3.22/1223;
8. build a fresh canonical USB from the promoted source;
9. repeat the clean Ubuntu 26.04 physical fresh-install from the beginning.
