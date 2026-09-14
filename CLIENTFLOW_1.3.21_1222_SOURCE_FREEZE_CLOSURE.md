# ClientFlow 1.3.21 / sequence 1222 — source-freeze security and hygiene closure

## Scope

This closure is the final source-hardening gate before sequence-1222 runtime-input
transport and canonical release build. It does **not** publish, approve or promote
1.3.21/1222 and does not change the runtime catalog.

Canonical pre-closure main:

- commit: `f19da0f0a602331e50dc37c2b42da44390e9658e`
- canonical push CI: `#683` / run `34778449650` -> `success`
- source identity: `1.3.21 / 1222`
- runtime catalog: `1.3.20 / 1221`

## Security closure

The frontend lock previously resolved transitive `nanoid` to `3.3.16` and carried
a temporary audit exception for `GHSA-2v37-7h3g-55p8`. The reviewed GitHub
Advisory Database now classifies `< 3.3.18` as affected on the 3.x line and
`3.3.18` as patched.

The source-freeze candidate therefore:

- resolves the existing PostCSS-compatible Nano ID 3.x dependency to exactly
  `3.3.18`;
- removes the `GHSA-2v37-7h3g-55p8` audit exception;
- locks the exact registry URL and integrity already published for 3.3.18;
- adds 3.3.18 to the existing frontend security-remediation runtime contract;
- does not use `npm audit fix --force`, does not change a major dependency and
  does not introduce unrelated dependency churn.

The canonical GitHub frontend job remains responsible for the authoritative
`npm ci`, dependency audit, complete frontend tests, lint and production build
under Node 22.22.0 / npm 10.9.4.

## Source hygiene closure

A top-level `repo-overlay/` directory contained 11 duplicate implementation/test
files from an earlier handoff. It was not referenced by the build, CI or release
paths and 7 of the 11 copies had already diverged from their canonical paths.
The directory is removed in full.

A source-freeze regression contract now fails if `repo-overlay/` is ever
reintroduced. Canonical files under `backend/`, `client/`, `frontend/` and
`scripts/` remain the only source authority.

The top-level `SHA256SUMS.txt` was also stale from already merged source changes.
The source-freeze closure refreshes every existing entry against current canonical
source, adds the new freeze/security inputs, and regression-gates the manifest so
missing, duplicate or mismatched entries fail CI.

## Release boundaries retained

This closure intentionally does not modify:

- `client/VERSION` (`1.3.21`);
- `client/release/release-input.json` sequence (`1222`);
- runtime catalog sequence/stable selection (`1221` / `1.3.20`);
- Livestream implementation;
- Terminal implementation;
- Remote Desktop implementation;
- release publication or catalog promotion state.

The exact post-merge source commit must be recorded externally after canonical
GitHub CI succeeds. A commit cannot safely self-assert its own final SHA.

## Next canonical gates

After this closure is merged and canonical push CI is green:

1. record the exact 40-character source-freeze commit SHA;
2. produce and verify the locked sequence-1222 runtime-input transport;
3. run the canonical release build twice for the exact same source SHA and
   runtime-input transport;
4. require byte-identical candidates and the Ubuntu 26.04 executable-candidate gate;
5. manually approve the exact reproducible candidate;
6. publish those exact bytes immutably and independently re-read size/SHA-256;
7. only then promote the separate runtime catalog to 1.3.21/1222;
8. perform a genuinely clean Ubuntu 26.04 physical fresh-install and final
   legacy-1.1.19 GUI/process parity acceptance.
