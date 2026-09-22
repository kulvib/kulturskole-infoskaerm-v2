# ClientFlow 1.3.25 / sequence 1226 — unused-file hygiene source-refreeze closure

## Scope

This is a narrow source-hygiene correction after the 1.3.25/1226 terminal-UX
refreeze and before runtime-input transport/build. It removes files proven to
be unused by the current runtime, installer, release tooling and CI contracts.

No release identity, catalog selector, database schema, authentication,
enrollment semantics, command cadence, runtime domain, update semantics or
security boundary is changed.

## Removed files

- `client/runtime/clientflow_runtime/release_download.py` — obsolete Bearer-based
  release downloader superseded by deployment-bound DPoP artifact authority;
- `client/config-examples/domain-credential.json` — enrollment materializes the
  real domain credentials; the template is never consumed;
- `client/config-examples/identity.json` — enrollment materializes the installed
  identity; the template is never consumed;
- `client/config-examples/root-grant.json` — enrollment materializes the root
  grant; the template is never consumed;
- `BASE_BLOBS.txt` — historical patch blob SHA inventory with no build, runtime,
  CI or release authority.

The remaining `client/config-examples/livestream.json` and
`remote-desktop.json` are intentionally retained because the canonical release
CLI consumes them.

## Test contract

Source tests now prove that the obsolete downloader and unused templates remain
absent instead of reading dead code as a negative example. The canonical DPoP
artifact endpoint contract, release identity contract and source checksum
contract remain enforced.

## Release boundary

Source/build identity remains:

- version `1.3.25`;
- sequence `1226`;
- candidate `clientflow-1.3.25-seq-1226`;
- migration head `20260922_56a_calendar_rev`.

The runtime catalog remains deliberately on approved 1.3.24/1225. After this
change is merged and canonical CI is green, the resulting fresh `main` commit
SHA supersedes every earlier 1226 source SHA and becomes the only valid source
for runtime-input transport and reproducible release build.
