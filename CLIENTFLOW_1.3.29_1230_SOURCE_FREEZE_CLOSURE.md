# ClientFlow 1.3.29 / sequence 1230 — physical-acceptance repair source freeze

## Scope

This is the source-freeze gate after the promoted 1.3.28/1229 clean Ubuntu
26.04 physical acceptance run exposed runtime defects in Remote Desktop,
Browser Guard consent cleanup and live calendar status colouring. The complete
fixes are already merged to canonical `main` and CI-green. This package stages
those merged bytes as ClientFlow 1.3.29 / sequence 1230 while deliberately
leaving the runtime selector on 1.3.28/1229 until a new immutable candidate has
crossed every required release gate.

Canonical pre-freeze source is the fresh `main` archive supplied on
2026-10-02. The archive contains no `.git` metadata, so no source commit SHA is
guessed or self-embedded here.

## Frozen candidate identity

- `client/VERSION = 1.3.29`;
- `release_sequence = 1230`;
- candidate release id: `clientflow-1.3.29-seq-1230`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`;
- database migration head: `20260929_58a_maintenance`.

## Catalog boundary

This freeze does not publish or promote the candidate. The runtime catalog
remains byte-for-byte on:

- catalog sequence `1229`;
- latest/default version `1.3.28`;
- selected release `clientflow-1.3.28-seq-1229`.

Regression contracts require source sequence 1230 to lead catalog sequence
1229 by exactly one until the new immutable approved bundle exists and has
been independently verified.

Immutable 1.3.27/1228 remains security-rejected historical evidence and is not
reintroduced into selectable metadata.

## Physical evidence carried into this freeze

The 1.3.28/1229 physical run already proved the following parts of the release
flow on Ubuntu 26.04.1 amd64/Wayland:

- canonical USB integrity and user-facing EXE entrypoint;
- factory/client preparation and kiosk autologin handoff;
- customer activation, exact release download/integrity and durable pending state;
- automatic post-reboot readiness reflected in Control Room without manual refresh;
- manual backend approval followed by automatic local activation without a
  manual service restart or extra reboot;
- active 1.3.28/1229 runtime, backend sync, calendar service, Browser Guard,
  display runtime and kiosk URL/config change with the required 10-second
  countdown;
- successful full-screen kiosk rendering.

The same run then exposed three release-blocking defects that are fixed in this
source freeze:

1. `clientflow-remote-desktop-agent.service` restarted continuously because its
   isolated service user attempted `chmod(0700)` on `/home/clientflow-kiosk`,
   which is owned by the kiosk account. The file channel now validates that
   external root without mutating its mode and reserves private-mode enforcement
   for the agent-owned staging root.
2. Browser Guard was active and reported successful consent acceptance, but a
   known overlay could remain visible after an ordinary browser start. The
   accepted path now activates the same hide/cleanup protection used for refresh
   handling, covering GUI/backend/boot starts, URL changes and browser reset.
3. The local status GUI kept the pre-approval `status-gray` class when calendar
   rows transitioned live to approved state, overriding newly applied green/red
   classes. Refresh now removes every prior status-colour class before applying
   the current one.

## Runtime and compatibility boundary

Python remains `3.13.14`. This repair release intentionally does not combine a
runtime-Python upgrade with the physical-acceptance fixes. The Python 3.13.15
candidate remains evidence only until the compatibility-bridge update proof
required by the release procedure is complete.

The next candidate acceptance must cover both the corrected fresh-install
runtime behaviour and the real 1.3.28 -> 1.3.29 in-place update path on the
existing physical client before any catalog promotion.

## Source-freeze decision

**PASS for source freeze**, subject to canonical GitHub CI after merge.

The next step is release mechanics: record the exact freeze SHA, produce the
source-SHA-qualified sequence-1230 runtime-input transport, build reproducible
candidate bytes, and physically validate those exact candidate bytes before
manual approval, immutable publication and catalog promotion.
