# ClientFlow 1.3.23 / sequence 1224 — source-freeze closure

> **SUPERSEDED BEFORE BUILD:** This initial freeze boundary is historical.
> Additional source changes were merged before sequence-1224 runtime-input
> transport, release build, approval, publication or catalog promotion. The
> current authority is `CLIENTFLOW_1.3.23_1224_SOURCE_REFREEZE_CLOSURE.md`.

## Scope

This is the source-freeze gate for the release carrying the merged factory →
customer handoff, legacy-aligned terminal UX and pre-activation local-GUI
closures. It allocates source/build identity 1.3.23/1224 while deliberately
leaving the runtime selector on the already approved and published 1.3.22/1223.

Canonical pre-freeze main:

- commit: `a969a7f046f748243e539f208d3c5e69c5585e72`;
- canonical push CI: `#722` / run `35429313779` / completed success;
- source identity before freeze: `1.3.22 / 1223`;
- runtime catalog: `1.3.22 / 1223`.

## Frozen candidate identity

- `client/VERSION = 1.3.23`;
- `release_sequence = 1224`;
- candidate release id: `clientflow-1.3.23-seq-1224`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`.

The exact post-merge Git commit is intentionally not self-embedded. The final
40-character source-freeze SHA must be recorded after canonical GitHub CI
succeeds.

## Catalog boundary

This freeze does not publish or promote the candidate. The runtime catalog
remains byte-for-byte on:

- catalog sequence `1223`;
- latest/default version `1.3.22`;
- selected release `clientflow-1.3.22-seq-1223`.

Regression contracts require the source sequence to lead the catalog by
exactly one and require the selector to stay on 1.3.22/1223 until the new
immutable 1.3.23/1224 bundle exists and has been independently verified.

## Lifecycle closure included

The frozen candidate contains the merged lifecycle changes proven by green
canonical main CI:

- office-side creation/validation of `cfadmin` and `clientflow-kiosk`;
- `cfadmin` password definition in **01**, never in customer **02**;
- kiosk Wayland autologin and kiosk-owned **02 Aktiver ClientFlow** after the
  shipping reboot;
- temporary exact-command, SHA-256-bound, no-argument `sudo -n` activation
  capability instead of a customer sudo prompt;
- broad saved NetworkManager-profile scrub and post-delete verification before
  shipping handoff;
- fail-closed schema-2 factory-state validation before canonical fresh install
  accepts pre-provisioned accounts;
- legacy-style terminal diagnostics and visible installation progress without
  secret exposure;
- staged-release pre-activation GUI after customer reboot while
  `clientflow.target` and full operational domains remain inactive;
- no `Skift til administrator` action in the local GUI;
- clean handoff from temporary pending GUI to the normal runtime GUI only after
  backend approval.

## Frozen implementation domains

Livestream, Terminal and Remote Desktop implementation domains are unchanged by
this source-freeze package.

## Next canonical gates

After merge and green canonical push CI:

1. record the exact source-freeze SHA;
2. build/verify the deterministic sequence-1224 runtime-input transport;
3. dispatch canonical `release-build.yml` for that exact SHA;
4. require byte-identical independent candidate outputs and Ubuntu 26.04
   executable-candidate PASS;
5. manually approve the exact candidate;
6. immutably publish and independently re-read the approved bytes;
7. separately promote catalog 1224 / 1.3.23;
8. regenerate the canonical USB;
9. restart physical Ubuntu 26.04 fresh-install acceptance from phase 0.
