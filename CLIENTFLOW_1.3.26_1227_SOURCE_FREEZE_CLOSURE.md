# ClientFlow 1.3.26 / sequence 1227 — final pre-release source-freeze closure

## Scope

This is the source-freeze gate after the post-1226 factory-readiness, Terminal,
Remote Desktop, local-GUI parity, Control Room configuration, kiosk-hardening,
Ubuntu-update safety and repository/database-performance audits. It stages the
complete merged source as ClientFlow 1.3.26 / sequence 1227 while deliberately
leaving the runtime selector on the already approved/published/promoted
1.3.25/1226 release until the immutable 1227 candidate has crossed every
required gate.

Canonical pre-freeze source is the fresh `main` archive supplied on 2026-09-27.
The archive contains no `.git` metadata, so no source commit SHA is guessed or
self-embedded here.

## Frozen candidate identity

- `client/VERSION = 1.3.26`;
- `release_sequence = 1227`;
- candidate release id: `clientflow-1.3.26-seq-1227`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`;
- database migration head: `20260922_56a_calendar_rev`.

## Catalog boundary

This freeze does not publish or promote the candidate. The runtime catalog
remains byte-for-byte on:

- catalog sequence `1226`;
- latest/default version `1.3.25`;
- selected release `clientflow-1.3.25-seq-1226`.

Regression contracts require source sequence 1227 to lead catalog sequence
1226 by exactly one until the new immutable approved bundle exists and has been
independently verified.

## Functional and kiosk closure

The frozen source retains the legacy 1.1.19 functional inventory and the V2
security/authority boundaries while adding the completed post-1226 closures:

- post-reboot factory readiness proof before backend approval;
- canonical Terminal UX/support checks without mutable repair workarounds;
- Remote Desktop file parity rooted at `/home/clientflow-kiosk` under
  least-privilege confinement;
- local GUI event/status/layout parity without exposing administrator access;
- domain-scoped Control Room configuration actions;
- kiosk-lockdown real observed-state verification and drift detection;
- permanent suppression of Ubuntu/GNOME notification banners in the kiosk session;
- permanent kiosk command-line protection without removing ClientFlow GUI,
  activation GUI or controlled Terminal authority;
- conservative non-removing Ubuntu update with package-health validation.

The user-switch/logout service path is intentionally preserved pending physical
runtime acceptance because it is the supported local path to the separate
password-protected `cfadmin` account; no administrator-switch control is exposed
inside the ClientFlow GUI.

## Database / performance closure

The source preserves the existing constant-query-budget and adaptive-polling
contracts. The 2026-09-27 repo audit found no evidence justifying speculative
query, index, polling or file-splitting changes before physical acceptance.
Runtime performance proof remains an acceptance item; UI responsiveness must not
be traded away merely to reduce Neon traffic.

## Source-freeze decision

**PASS for source freeze**, subject to canonical GitHub CI after merge.

The next step is release mechanics: record exact freeze SHA, prepare deterministic
runtime-input transport 1227, produce reproducible candidate bytes, and stage
those exact bytes for physical Ubuntu 26.04 acceptance before approval/publication
and later catalog promotion.
