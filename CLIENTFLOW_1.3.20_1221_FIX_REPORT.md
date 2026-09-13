# ClientFlow 1.3.20 / sequence 1221 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the
physical-harvest fixes and Display lifecycle hotfix 2 have passed their CI
gates and were merged to `main`. The exact base-main push CI run was also
verified green before allocating the new identity.

Base source before this identity transition:

- main commit: `03e2125a29e38bd95dcfb7dd1e1beda2296ae02c`
- source identity: `1.3.19 / 1220`
- runtime catalog: `clientflow-1.3.19-seq-1220`
- canonical base-main push CI: run `#654`, conclusion `success`

Staged source/build identity after this change:

- version: `1.3.20`
- release sequence: `1221`
- candidate release id: `clientflow-1.3.20-seq-1221`

This file is **not** an approval, publication or catalog-promotion record.

## Release-gate separation

The runtime catalog deliberately remains on the last approved and immutably
published release:

- `catalog_sequence = 1220`
- `latest_stable = 1.3.19`
- `default_install_version = 1.3.19`
- selected release = `clientflow-1.3.19-seq-1220`

The source/build identity is allowed to lead that catalog by exactly one
sequence while 1.3.20/1221 passes the canonical release-build, reproducibility,
manual approval and immutable publication gates.

Only after the exact approved 1.3.20/1221 bundle has been independently
verified in the canonical immutable artifact store may a separate catalog
promotion make it selectable for fresh install or update.

## Included functional closure

The 1.3.20/1221 candidate source contains the previously merged physical
failure closure:

- first-activation helper dispatches to the immutable staged release CLI;
- pre-activation GDM/AccountsService login baseline is materialized before the
  controlled reboot;
- first activation still requires the canonical kiosk seat0 Wayland session;
- activation health excludes only explicitly marked optional units;
- Browser Guard suppresses intentional Chrome-off noise without hiding the
  reachable-Chrome/no-main-page condition;
- local GUI carries the deployed legacy 1.1.19 visual/message contract plus
  the required V2 operational fields and safe actions.

Livestream, Terminal and Remote Desktop implementation domains remain frozen.

## Local validation of this transition

- Python compile for the changed/release-relevant source: **PASS**
- identity/catalog/procedure focused gate: **35/35 PASS**
- broader release/build/publication/fresh-install gate runnable in this container: **109/109 PASS**
- full backend integration collection is not claimed locally because the analysis container lacks repo-CI dependencies such as `sqlmodel`; GitHub CI remains authoritative.
- Ruff is not claimed locally because the repo-pinned Ruff executable is not installed in the analysis container.
- changed runtime implementation files: **none**

## Next canonical gates

1. Merge this source-identity transition only after full GitHub CI is green.
2. Record the resulting exact 40-character source commit SHA.
3. Run `.github/workflows/release-build.yml` for that exact SHA and the locked
   runtime-input transport.
4. Require the two independent runner outputs to be byte-identical.
5. Manually approve the exact reproducible candidate.
6. Publish the exact approved bytes immutably.
7. Independently verify the immutable store.
8. Only then create the separate runtime-catalog promotion to 1.3.20/1221.
9. After catalog promotion, perform canonical physical Ubuntu 26.04 fresh-install
   verification and physical GUI parity acceptance.
