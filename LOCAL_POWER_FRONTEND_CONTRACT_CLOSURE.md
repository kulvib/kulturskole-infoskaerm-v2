# ClientFlow local power + obsolete frontend contract closure

## Scope

This source batch closes the remaining L119-13 local reboot/shutdown attribution gap and the UI-facing part of L119-14.

No release identity, catalog selection, credential model, migration, Display command path, Livestream, Terminal or Remote Desktop code is changed.

## L119-13 — local reboot/shutdown attribution

### Defect

Canonical System commands already reconcile backend-requested reboot/shutdown using boot-id evidence. A reboot or shutdown initiated locally through GNOME, cfadmin or another host-local control path bypasses that command queue and therefore had no V2 source attribution.

### Trigger

A human or local desktop tool reboots/powers off the Ubuntu host without first receiving a canonical System command.

### Consequence

After reconnect, Status proves a new boot but the backend cannot distinguish an ordinary detected boot from a locally initiated reboot/shutdown. This is below the legacy 1.1.19 functional acceptance level.

### Root cause

V2 retained canonical remote System command reconciliation but removed the durable local transition marker/reporting path.

### Fix

- root-only reboot/poweroff target hooks write a small non-secret durable transition marker;
- the existing System broker writes a short-lived same-boot intent before canonical backend power commands;
- matching System intent suppresses local attribution, preventing double authority;
- after a different boot id is observed, the read-only Status agent includes the local event as observed telemetry;
- backend validates event/action/source/boot binding and persists only compatibility lifecycle metadata;
- the event can never create, claim, complete or mutate a canonical System command;
- release activation explicitly enables the reboot/poweroff hooks only after runtime health, disables them during release swaps/pending rollback, and wipe disables them before managed units are removed.

### Frozen risk

The implementation changes Status/System shared platform code only because the documented defect is in power lifecycle attribution. Livestream, Terminal and Remote Desktop source is untouched. Display source is untouched.

### CI correction — opaque boot-id contract

The first CI run exposed a contract regression in the new attribution layer: `requested_boot_id` was parsed as a UUID and compared to the local kernel boot id. The established Status/System HTTP contract intentionally treats boot ids as bounded opaque strings (`max_length=128`), and the operational integration flow uses values such as `boot-a`/`boot-b`.

The correction preserves that authority boundary:
- backend-reported/requested boot ids remain bounded opaque strings;
- only `/proc/sys/kernel/random/boot_id`, which is read locally from Linux, is UUID-validated;
- local reporter suppression is bound to that actual same-host kernel boot id, not to the representation chosen by the backend Status contract;
- event ids remain UUIDs.

### Regression

Tests cover:
- local reboot marker across a boot-id change;
- canonical System intent suppressing false local attribution;
- wrong/stale binding not suppressing a local event;
- reporter systemd target wiring;
- explicit release enable/disable lifecycle;
- Status/System use of non-secret evidence only;
- backend boot-binding validation in the full CI environment.

## L119-14 — obsolete frontend contracts

Current canonical backend deliberately rejects `desktop_lockdown_enabled` because no canonical runtime consumer exists. Keeping a disabled “Kiosk lockdown” control visible implied a capability the product does not currently have.

The control, status copy and live-poll fields are therefore removed from the frontend. The historical backend/database compatibility fields remain fail-closed; they are not release authority and are not exposed as an actionable frontend feature.

Existing canonical ClientFlow deployment APIs remain the only frontend ClientFlow update path; legacy `client_update_*` controls remain absent.

## Release identity

This batch does not promote or rebuild an approved release. Source remains the current 1.3.18 / sequence 1219 candidate while catalog authority remains 1.3.17 / sequence 1218 until the release gate is completed.
