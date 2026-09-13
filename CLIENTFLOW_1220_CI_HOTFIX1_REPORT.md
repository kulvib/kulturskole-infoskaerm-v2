# ClientFlow 1.3.19 / sequence 1220 — physical-harvest CI hotfix 1

## Purpose

This is a complete replacement changed-files package for branch
`fix/clientflow-1220-physical-harvest`.

It corrects the first package after full GitHub CI exposed three contract
regressions.  It deliberately **does not promote** the source to the next
release identity yet.

Canonical branch/source identity remains:

- version: `1.3.19`
- release sequence: `1220`
- approved runtime catalog: `clientflow-1.3.19-seq-1220`

The next release identity (`1.3.20` / `1221`) is created only after the full
repository CI is green.

## CI failures corrected

### 1. Release identity was promoted too early

`client/VERSION` and `client/release/release-input.json` are restored to
`1.3.19` / `1220`, matching the still-approved backend release catalog.
No catalog metadata is changed.

### 2. Local GUI lost required V2 operational fields

The legacy-layout port now retains the existing V2 `Auto refresh` field and
binds it to `browser_refresh_interval_sec` from the canonical Display
configuration.

### 3. Local GUI lost the safe administrator switch

`Skift til administrator` and `SWITCH_USER_HELPER` are restored.  The GUI
invokes only the existing canonical `clientflow-switch-user-admin` helper with
no shell and a bounded timeout.  It does not implement session switching itself.

The two legacy primary actions (`Start kiosk` / `Stop kiosk`) remain equal-width
on the first action row.  The V2 administrator switch is a subordinate second
row action so it does not change the legacy primary-button geometry.

## Legacy visual contract versus required V2 extensions

The deployed 1.1.19 GUI remains the visual/style authority:

- GUI SHA-256: `027804da4cf3e722ce42a6d7760aa55a1a8f30d901bfc532a1cf63e22d5ba936`
- status map SHA-256: `9e6f01fbbe4b23f1458cc2740cea1bc43777499f8d4da3bd83f2a474fb7e74b4`

Two V2 capabilities that already existed before this parity work are preserved
as explicit extensions rather than removed for cosmetic equality:

- `Auto refresh` in Kioskinfo;
- `Skift til administrator` in Handlinger.

All legacy colors, typography rules, section order, responsive panel ratios,
copy affordances, status wording, calendar presentation and Start/Stop primary
geometry remain governed by the deployed 1.1.19 reference.

## Existing physical-harvest fixes retained

- `CF-1220-DISPATCH-01`: staged immutable release CLI dispatch.
- `CF-1220-DISPLAY-01`: controlled pre-activation reboot/session boundary.
- `CF-1220-HEALTH-01`: explicit optional activation-health marker only.
- `CF-1220-OBS-01`: Browser Guard quiet while Chrome is intentionally unavailable.

## Frozen-domain guarantee

No Livestream, Terminal or Remote Desktop implementation file is changed.
The GUI has explicit read-only `_service_state(...)` observations for these
frozen domains and performs no domain mutation.

## Test-oracle change

`backend/tests/test_display_operational_parity_54a_source.py` previously pinned
the transitional GTK size `self.set_default_size(820, 900)`.  That assertion
conflicts with the later explicit requirement to use the deployed 1.1.19
responsive visual contract.  It is replaced by stronger checks for the 43% / 98%
responsive ratios, max width 900, non-resizable behavior and dynamic sizing.

No functional assertion is weakened to hide a product defect.

## Validation completed in changed-files context

- compile-all changed tree: PASS
- focused physical-harvest regression suite: 9/9 PASS
- relevant existing fresh-install tests: 3/3 PASS
- existing Display operational-parity GUI test: PASS in reconstructed client context
- existing Legacy119 Local GUI source contract: PASS by exact assertion-equivalent check
- release source identity versus current approved catalog: PASS (`1.3.19` / `1220`)
- frozen-domain changed-file check: PASS

## Still required

- full GitHub `python -m pytest -q backend/tests scripts/tests` after applying this package;
- all other GitHub CI jobs;
- only after full green CI: separate next-release identity change to 1.3.20 / 1221;
- reproducible candidate build/approval;
- canonical physical fresh-install verification;
- physical screenshot comparison for final GTK4/Wayland GUI acceptance.
