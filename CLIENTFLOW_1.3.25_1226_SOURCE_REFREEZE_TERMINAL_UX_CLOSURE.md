# ClientFlow 1.3.25 / sequence 1226 — terminal-UX source-refreeze closure

## Scope

This is the single deliberate source correction after the initial 1.3.25/1226
source-freeze and before runtime-input transport/build. It implements the
operator-reviewed terminal copy from the 2026-09-22 terminal-dialog document.

No release identity, catalog selector, database schema, authentication,
enrollment semantics, command cadence, runtime domain, update semantics or
security boundary is changed.

## Visible terminal changes

- new-client input is shortened to `Klientnavn:`;
- confirmation and reboot prompts display lowercase `[j/n]` while preserving
  their existing default behaviour;
- cfadmin/account success copy is shortened without changing validation;
- customer-launcher implementation details are no longer printed in the normal
  factory flow;
- phase 5 is labelled `Glem factory-netværk`;
- the factory completion sentence no longer prints the internal client-secret
  implementation note;
- locality is shortened to `Lokation/rum (valgfri, Enter = tom):`;
- the explanatory CF-code formatting sentence is removed while the formatted
  editor itself remains unchanged;
- approval/activation completion copy is shortened;
- the countdown now prints `1 sekund` and plural `sekunder` otherwise.

## Canonical installer JSON boundary

The canonical release CLI remains machine-readable by default. Direct
engineering invocation therefore still prints its final JSON result.

Only the normal `02 Aktiver ClientFlow` bootstrap invokes the canonical install
operation with the hidden `--suppress-result-json` presentation flag. Live
`[INSTALL]`/`[OK]` progress remains visible. The installation result, durable
`pending_manual_activation` state and all fail-closed validation are unchanged.

## Release boundary

Source/build identity remains:

- version `1.3.25`;
- sequence `1226`;
- candidate `clientflow-1.3.25-seq-1226`;
- migration head `20260922_56a_calendar_rev`.

The runtime catalog remains deliberately on approved 1.3.24/1225. After this
change is merged and canonical CI is green, the resulting fresh `main` commit
SHA replaces the earlier pre-correction SHA as the only valid 1226 source SHA
for runtime-input transport and reproducible release build.
