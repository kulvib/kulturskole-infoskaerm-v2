# ClientFlow 1.3.24 / sequence 1225 — source-freeze closure

## Scope

This is the source-freeze gate for the release carrying the merged Ubuntu 26.04
factory-handoff repairs discovered during physical acceptance of immutable
1.3.23/1224. It allocates source/build identity 1.3.24/1225 while deliberately
leaving the runtime selector on the already approved, published and promoted
1.3.23/1224 release until a new immutable candidate has crossed every release
gate.

Canonical pre-freeze main:

- commit: `91b82d6517ee9eafc0d5097fc872065793b687e4`;
- canonical push CI: `#775` / run `35510501782` / completed success;
- source identity before freeze: `1.3.23 / 1224`;
- runtime catalog: `1.3.23 / 1224`;
- physical status of immutable 1.3.23/1224: **FAIL** during factory handoff.

## Frozen candidate identity

- `client/VERSION = 1.3.24`;
- `release_sequence = 1225`;
- candidate release id: `clientflow-1.3.24-seq-1225`;
- Ubuntu minimum: `26.04`;
- architecture: `amd64`;
- runtime Python: `3.13.14`.

The exact post-merge Git commit is intentionally not self-embedded. The final
40-character source-freeze SHA must be recorded after canonical GitHub CI
succeeds.

## Catalog boundary

This freeze does not publish or promote the candidate. The runtime catalog
remains byte-for-byte on:

- catalog sequence `1224`;
- latest/default version `1.3.23`;
- selected release `clientflow-1.3.23-seq-1224`.

Regression contracts require the source sequence to lead the catalog by
exactly one and require the selector to stay on 1.3.23/1224 until the new
immutable 1.3.24/1225 bundle exists and has been independently verified.

## Physical failure closures included

The frozen candidate contains the already merged canonical repairs proven from
physical Ubuntu 26.04 diagnostics:

- `CF-1224-SUDO-RS-01`: remove unsupported sudo digest syntax while retaining
  an exact-path, no-arguments-only, root-owned and `visudo`-validated temporary
  activation capability;
- `CF-1224-NETPLAN-CLEANUP-02`: remove persistent Netplan shipping-network
  subtrees as well as current NetworkManager profiles, regenerate backend
  state, and fail closed if shipping profiles can still be regenerated;
- `CF-1224-SYSTEMD-INHIBITOR-HARDENING-03`: use
  `systemctl --check-inhibitors=no` for controlled reboots on systemd 259.

The failed immutable 1.3.23/1224 bytes are historical evidence and remain
unchanged.

## Frozen implementation domains

Livestream, Terminal and Remote Desktop implementation domains are unchanged by
this source-freeze package.

## Next canonical gates

After merge and green canonical push CI:

1. record the exact source-freeze SHA;
2. build/verify the deterministic sequence-1225 runtime-input transport;
3. dispatch canonical `release-build.yml` for that exact SHA;
4. require byte-identical independent candidate outputs and Ubuntu 26.04
   executable-candidate PASS;
5. manually approve the exact candidate;
6. immutably publish and independently re-read the approved bytes;
7. separately promote catalog 1225 / 1.3.24;
8. regenerate the canonical USB;
9. restart physical Ubuntu 26.04 fresh-install acceptance from phase 0.
