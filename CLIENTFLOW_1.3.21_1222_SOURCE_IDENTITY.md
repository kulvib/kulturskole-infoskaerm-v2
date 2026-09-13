# ClientFlow 1.3.21 / sequence 1222 — staged source/build identity

## Status

This change allocates the next ClientFlow source/build identity after the
physical Ubuntu 26.04 fresh-install of 1.3.20/1221 exposed
`CF-1221-REBOOT-01` and the narrow reboot-inhibitor fix was merged to `main`
after its canonical CI gate.

Base source before this identity transition:

- main commit: `7d4eb6d13339fc7718051f457eb1f76cf178075b`
- source identity: `1.3.20 / 1221`
- canonical base-main push CI: run `#667` (`34770406562`), conclusion `success`
- runtime catalog: `clientflow-1.3.20-seq-1221`
- physical status of immutable 1.3.20/1221: canonical fresh-install **FAIL** at the controlled pre-activation reboot because the active GNOME session held a block shutdown inhibitor
- source fix: `systemctl --no-block --ignore-inhibitors reboot`, guarded by durable `pending_manual_activation` plus exact release binding, with no `--force`

Staged source/build identity after this change:

- version: `1.3.21`
- release sequence: `1222`
- candidate release id: `clientflow-1.3.21-seq-1222`

This file is **not** an approval, publication or catalog-promotion record.

## Release-gate separation

The runtime catalog deliberately remains on the last approved and immutably
published release:

- `catalog_sequence = 1221`
- `latest_stable = 1.3.20`
- `default_install_version = 1.3.20`
- selected release = `clientflow-1.3.20-seq-1221`

The source/build identity is allowed to lead that catalog by exactly one
sequence while 1.3.21/1222 passes the canonical release-build,
reproducibility, manual approval and immutable publication gates.

The catalog must not select 1.3.21/1222 until its exact approved bundle has
been published to the canonical immutable store and independently re-read at
the expected size and SHA-256.

## Included functional closure

The 1.3.21/1222 candidate source contains the already merged physical-failure
closures from the previous cycle, including:

- immutable staged activation dispatch instead of ordinary stable-updater activation;
- pre-activation GDM/AccountsService kiosk-login materialization;
- strict `clientflow-kiosk` seat0 Wayland readiness for activation;
- explicit optional activation-health semantics;
- Browser Guard intentional-Chrome-off quieting;
- deployed legacy 1.1.19 local-GUI visual/message contract with required V2 fields;
- `CF-1221-REBOOT-01` closure: the controlled pre-activation reboot uses the narrow systemd inhibitor override `--ignore-inhibitors`, never `--force`, after durable pending state and exact release binding are verified.

Livestream, Terminal and Remote Desktop implementation domains remain frozen.

## Physical evidence retained

The failed 1.3.20/1221 physical run remains authoritative historical evidence:
installation and exact bundle staging succeeded, `pending_manual_activation`
was durable, account provisioning was correct, the graphical login baseline
completed with `DISPLAY_SESSION_PREPARE_OK`, and only the controlled reboot
transition failed. 1.3.20/1221 is not hotfixed in place.

## Next canonical gates

1. Merge this identity-only transition only after full GitHub CI is green.
2. Record the resulting exact 40-character source commit SHA.
3. Produce/verify the locked runtime-input transport for sequence 1222.
4. Run `.github/workflows/release-build.yml` for that exact source SHA.
5. Require byte-identical independent candidate outputs and Ubuntu 26.04 executable-candidate PASS.
6. Manually approve the exact reproducible candidate.
7. Publish the exact approved bytes immutably and independently re-read them.
8. Only then create the separate runtime-catalog promotion to 1.3.21/1222.
9. Repeat the canonical clean Ubuntu 26.04 physical fresh-install from a genuinely clean host, with no diagnostic bypass.
10. Complete physical GUI pixel-parity acceptance against deployed legacy 1.1.19.
