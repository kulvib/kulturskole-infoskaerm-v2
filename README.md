# Kulturskole Infoskærm v2

Canonical source repository for PlanIQ Display / ClientFlow.

The repository is under active construction and review. The goal of the v2 baseline is to represent the currently validated architecture directly, without historical installer overlays or legacy control-plane paths.

## Repository layout

```text
.
├── backend/                  FastAPI backend, Alembic migrations and tests
├── frontend/                 React/Vite frontend and tests
├── client/
│   ├── runtime/              Canonical ClientFlow runtime source
│   ├── systemd/              Canonical systemd definitions
│   ├── sysusers.d/           ClientFlow system-user definitions
│   ├── tmpfiles.d/           Runtime/state directory definitions
│   ├── config-examples/      Installed configuration templates
│   ├── libexec/              Fixed-function privileged helpers
│   └── release/              Release transaction, builder inputs and docs
├── scripts/                  Repository/release validation and build tools
└── render.yaml               Current Render deployment configuration
```

## Runtime domains

ClientFlow has separate functional/security domains:

- Status
- Display
- System
- Livestream
- Terminal
- Remote Desktop

Status, Display and System share the reviewed shared-domain control plane. Livestream, Terminal and Remote Desktop own isolated credentials and runtime/session state.

The physically validated Livestream, Terminal and Remote Desktop runtime behavior is treated as frozen baseline. Structural changes around packaging, provisioning or shared infrastructure must not change their functional runtime behavior without a documented root cause and physical regression test.

## Database

Alembic is authoritative for schema changes. Application startup must not create or mutate database schema implicitly.

Run migrations from `backend/` through:

```bash
python scripts/run_migrations.py
```

The canonical shared-foundations base is `20260819_50a_canonical`; the current reviewed head is `20260819_51a_update_control`, which adds first-class ClientFlow deployment authority and the stable update-credential schema.

## ClientFlow release model

ClientFlow uses a keyless runtime-release model with explicit fresh-install and in-place-update modes:

- source version: `client/VERSION`
- monotonically increasing sequence: `client/release/release-input.json`
- canonical runtime wheel is rebuilt from `client/runtime/` for every release candidate
- offline Python/runtime dependency inputs are supplied separately and are not committed as source
- release candidates are non-deployable by default
- manifest schema 7 declares `artifact_type: runtime_release`, explicit `install_modes`, and the exact fresh-installer file/size/SHA-256
- backend deployment authority is derived from the exact approved bytes published in `CLIENTFLOW_RELEASE_ARTIFACT_DIR`
- artifact download requires a deployment-bound, DPoP-bound updater authorization; legacy System-domain bearer tokens are not accepted
- a separate explicit approval step binds approval to the exact candidate SHA-256, source commit, and fresh-installer SHA-256
- installation/activation is manual; no automatic reboot or automatic activation is permitted

See:

- `client/release/docs/CLIENTFLOW_RELEASE_AND_ROLLBACK.md`
- `client/release/docs/CLIENTFLOW_INSTALLATION.md`
- `CLIENTFLOW_RELEASE_PROCEDURE.md`

## Development checks

Backend source-contract checks:

```bash
python -m pytest -q backend/tests/test_*source*.py
```

Frontend:

```bash
cd frontend
npm ci
npm run build
```

Client runtime/release code should compile before a release candidate is built:

```bash
python -m compileall -q client/runtime client/release/lib scripts backend/service1 backend/migrations
```

## Review principle

Actual source code is the implementation source of truth. Physical Ubuntu tests are the source of truth for observed runtime behavior. Documentation supports the review but does not override working, physically verified behavior.

Changes to runtime behavior require a documented category A/B finding, root cause and relevant regression plan. Production-readiness hardening is handled separately from the current correctness/isolation review.
