# Dependency- og runtimevedligeholdelse – PlanIQ Display

## Fastlåste runtimes

- Backend/CI Python: `3.13.16`
- Node.js: `24.21.0` LTS
- npm: `11.19.0`
- ClientFlow 1.3.30/1231 embedded runtime Python: `3.13.14` (compatibility boundary; intentionally unchanged until an authentic physical in-place runtime bridge is proven)
- pip i Render/CI: `26.1.2`

Render, GitHub Actions, `backend/.python-version`, `frontend/package.json` og lockfilerne skal ændres samlet for backend/frontend toolchains.

ClientFlow release-artifact production is a separate compatibility boundary. The 1.3.30/1231 release line remains on embedded Python `3.13.14` until an authentic physical in-place runtime bridge has been proven; the general backend/CI runtime does not share that freeze. Both backend and embedded-runtime PyJWT remain pinned to `2.15.1`. The deterministic Python `3.13.15` embedded-runtime candidate remains historical/candidate evidence and is not adopted by 1.3.30/1231.

## Python

`backend/requirements.txt` indeholder eksakte direkte produktionsafhængigheder. `backend/requirements.lock.txt` og `requirements-ci.lock.txt` indeholder den fulde resolverede graf med SHA-256-hashes.
Backendens `cryptography`-pin er `50.0.2`; lockfilerne indeholder kun godkendte SHA-256-hashes for den resolverede artifact-kæde.

Installation og kontrol:

```bash
python -m pip install --upgrade pip==26.1.2
python -m pip install --require-hashes -r requirements-ci.lock.txt
python -m pip check
python -m pip_audit --disable-pip --no-deps --progress-spinner off -r backend/requirements.lock.txt
python scripts/validate_dependency_contract.py
python -m pytest -q backend/tests scripts/tests
```

Lockfiler skal genereres fra rene Python 3.13-miljøer og må ikke indeholde interne index-URL'er eller credentials.

## ClientFlow release-build toolchain

Release artifact production has its own narrower deterministic toolchain contract in `client/release/release-build-toolchain.json`. The canonical workflow pins Python `3.13.14`, pip `26.1.2`, and setuptools `83.0.0`; the setuptools wheel is installed with hashes from `client/release/release-build-requirements.lock.txt`. `client/runtime/pyproject.toml` must declare the same setuptools build backend version.

Changing this toolchain is a release-format/build-input change: update the toolchain contract, hash lock, pyproject build requirement and release-build tests together, then prove two-runner byte-for-byte reproducibility before approving a candidate.

## Frontend

`npm ci` er den eneste installation i CI og Render. `frontend/package-lock.json` er source of truth.

```bash
cd frontend
npm ci
npm run audit:dependencies
npm run test:dependency-runtime
npm run lint
npm run test:api-error
npm run test:remote-desktop-urls
npm run build
```

Audit-undtagelser skal være specifikke, tidsbegrænsede og dokumenterede i `frontend/dependency-audit-allowlist.json`. Nye eller udløbne advisories blokerer CI.

## Produktspecifik status

Display bevarer HLS-, WebSocket-, ClientFlow- og Remote Desktop-afhængighederne. Dependency-opdateringer må ikke kombineres med produktændringer.
