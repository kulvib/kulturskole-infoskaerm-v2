# ClientFlow 1.3.20 / sequence 1221 — physical failure fix package

## Baseline

Physical failure harvesting was performed against immutable approved release:

- release: `clientflow-1.3.19-seq-1220`
- source commit: `e51dcccf88b50b90e53e73808703e62f355e8622`
- approved bundle SHA-256: `72870fcb512f51b20feb2a22bdaa41b75186b37643488a6af3d69e9efdf06c72`
- approved bundle size: `223078400`

This package proposes the next source identity:

- version: `1.3.20`
- release sequence: `1221`

It is a changed-files package only. It does not modify Viborg2 and does not modify immutable release 1.3.19/1220.

## Fixed confirmed defects

### CF-1220-DISPATCH-01 — fixed

The fresh-install activation helper no longer sends ordinary `activate` to the stable updater. Pending first activation invokes the immutable staged release directly through:

`<staged-release>/runtime/bin/python -P -m clientflow_release activate ...`

The exact staged release ID and immutable approval reference remain mandatory. Python user-site and bytecode writes are disabled and `PYTHONPATH` is scoped to the staged release.

### CF-1220-DISPLAY-01 — fixed at lifecycle level

Fresh install now has an explicit controlled pre-activation session boundary:

1. installer completes and writes durable `pending_manual_activation` state;
2. the bootstrap helper re-reads and validates that durable pending state and exact release binding;
3. only then does it queue one controlled reboot;
4. GDM can establish the canonical `clientflow-kiosk` Wayland session;
5. pending activation requires an existing local `clientflow-kiosk`, seat0, non-remote, Wayland session and foregrounds it before invoking the canonical staged activation CLI.

Release-CLI metadata now says `pre_activation_reboot_required: true`; it does not falsely claim that the release CLI itself performs the reboot.

### CF-1220-HEALTH-01 — fixed narrowly

Activation health no longer treats the explicitly optional quick-settings guard as mandatory-active. The service carries the explicit marker:

`# ClientFlow-Activation-Health: optional`

`_expected_active_units()` excludes only units with that marker. Generic `Condition*=` units are **not** ignored, preserving fail-closed behavior for required credential/prerequisite units.

### CF-1220-OBS-01 — fixed

Browser Guard now distinguishes:

- DevTools/Chrome unavailable: expected while Chrome is intentionally stopped; quiet by default;
- Chrome reachable but no main HTTP(S) page target: still emits the useful periodic summary.

Browser Guard internal version is advanced from `1.6.5` to `1.6.6`.

## GUI legacy parity

`client/libexec/local-gui` has been reworked against the actual GUI and status-map files shipped in the deployed 1.1.19 installer payload. See `GUI_PARITY_1.1.19.md`.

Source-level visible contract is PASS. Physical pixel-level acceptance remains required on the target GTK4/Wayland client.

## Frozen-domain guarantee

No source files belonging to these frozen domains are included in this package:

- Livestream
- Terminal
- Remote Desktop

The local GUI only reads their service liveness for legacy Systeminfo presentation; it does not change their implementations or control contracts.

## Validation completed

- Python compile of all package Python/executable Python sources: **PASS**
- New focused regression suite: **9 passed**
- Relevant modified existing fresh-install tests runnable in changed-files context: **3 passed, 5 deselected**
- Dynamic activation-health behavior: optional marked service excluded; required Condition-gated service retained: **PASS**
- Dynamic Browser Guard distinction (`DevTools unavailable -> None`, reachable empty target list -> `[]`): **PASS**
- Frozen-domain changed-file check: **PASS**
- Deployed legacy GUI SHA reference verified: **PASS**
- Deployed legacy status-map SHA reference verified: **PASS**

## Validation not claimed yet

This changed-files working tree is not a complete repository checkout. Therefore this package does **not** claim:

- full repository CI PASS;
- full backend/frontend test-suite PASS;
- release artifact reproducibility PASS for 1.3.20/1221;
- physical fresh-install PASS;
- physical GUI pixel-parity PASS.

Those are the next gates after applying the package to a fresh branch based on the canonical repository baseline.
