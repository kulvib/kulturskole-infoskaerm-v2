# Dependency- og runtimevedligeholdelse – PlanIQ Display

## Fastlåste runtimes

- Python: `3.13.14`
- Node.js: `22.22.0`
- npm: `10.9.4`
- pip i Render/CI: `26.1.2`

Render, GitHub Actions, `backend/.python-version`, `frontend/package.json` og lockfilerne skal ændres samlet.

## Python

`backend/requirements.txt` indeholder eksakte direkte produktionsafhængigheder. `backend/requirements.lock.txt` og `requirements-ci.lock.txt` indeholder den fulde resolverede graf med SHA-256-hashes.

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
