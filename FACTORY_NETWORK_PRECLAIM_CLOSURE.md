# ClientFlow factory/network preclaim lifecycle closure

Branch: `fix/factory-network-preclaim-lifecycle`

Fresh-main archive SHA256 reviewed: `d8f6a7b2a4c4025796d1ba0b0e5d806c50a9b9f1c2423b49c8f947b18f07e5b8`
Client VERSION: `1.3.18`
Release sequence: `1219`
Catalog authority remains `1.3.17 / 1218`.

## Classification

**B/C – factory/network fresh-install lifecycle parity.**

## Failure / trigger / consequence

Before this closure, V2 could enter a consuming fresh-install claim without a bounded NetworkManager/backend-readiness proof, could silently fall back to hostname for the client name, did not preserve explicit name/locality as local resume identity, did not project WiFi/LAN IP/MAC facts into enrollment, and had no safe equivalent of legacy temporary factory-network cleanup.

Legacy 1.1.19 proved the desired operator effect but its broad `cf_forget_saved_networks()` behavior deleted every saved NetworkManager WiFi/Ethernet/VPN profile. That deletion model is intentionally **not** copied into V2 because it is not multiclient/site-safe.

## Root cause

The V2 fresh installer treated network availability as an implicit prerequisite of the later HTTP claim. `--name`/`--locality` were forwarded directly to backend but were not locally frozen across resume. No bootstrap network profile ownership metadata existed, and enrollment host facts omitted the backend's existing WiFi/LAN fields.

## Closure

1. Brand-new fresh install requires an explicit non-empty client name before enrollment authorities are read.
2. Locality remains optional but is normalized and persisted.
3. Name/locality become immutable non-secret lifecycle fields for crash/resume.
4. After the existing apt/curl host-readiness gate, the real Ubuntu host must prove:
   - `/usr/bin/nmcli` exists;
   - NetworkManager reports `running`;
   - at least one non-loopback NetworkManager device is connected;
   - the configured backend `/health` returns canonical `{"status":"ok"}` over the configured TLS path.
5. The network preflight occurs before `_fresh_install_authorities(args)` and before new ClientFlow filesystem state.
6. Enrollment host facts now populate the backend's existing WiFi/LAN IP/MAC fields from `/sys/class/net` + `ip`; no schema or migration is introduced.
7. An operator may explicitly mark one currently active WiFi/Ethernet NetworkManager UUID as temporary bootstrap connectivity.
8. The exact UUID/type/name is persisted through `pending_manual_activation`.
9. After durable healthy first activation, only that exact marked profile may be deleted.
10. UUID reuse/type/name drift is rejected; arbitrary saved profiles are never enumerated for deletion.
11. Activation lifecycle state is durably recorded before optional network cleanup. A cleanup failure leaves an explicit pending marker for same-release retry instead of pretending activation failed or deleting another profile.

## Legacy equivalence

- Wired/WiFi/backend reachability: architecturally replaced by a fail-closed V2 preclaim readiness gate.
- Client name: preserved as explicit operator input and backend claim field.
- Locality: preserved as optional operator input and backend claim field.
- WiFi/LAN facts: restored through existing backend enrollment fields.
- Temporary factory-network cleanup: preserved with a narrower, safer explicit-ownership model. Legacy's delete-all-saved-connections behavior is obsolete because it can remove customer/site connectivity that ClientFlow did not create or mark.

## Frozen risk

No Livestream, Terminal or Remote Desktop source, unit, credential, protocol or runtime state is changed. No Display/System runtime source is changed. The change is isolated to the fresh-install release/enrollment plane plus tests/docs.

## Required regression

- no explicit client name -> fail before enrollment;
- no active NetworkManager connection -> fail before enrollment;
- backend `/health` not canonical healthy -> fail before enrollment;
- explicit active WiFi/Ethernet UUID -> exact marker persisted;
- inactive/non-WiFi/Ethernet UUID -> reject;
- cleanup deletes only exact recorded UUID/type/name;
- UUID/name/type drift -> reject without deletion;
- name/locality/marker survive pending transition;
- enrollment host facts include bounded WiFi/LAN projection;
- preclaim ordering remains host readiness -> network readiness -> authority read -> state mutation -> claim;
- full existing scripts regression remains green.

## Still open after this batch

Legacy GTK GUI parity, full capability-based parity gate, periodic time integrity, quick-settings parity, popup baseline for both human accounts, bounded local recovery/support UX, local reboot/shutdown attribution review, and obsolete frontend/backend contract cleanup remain open.
