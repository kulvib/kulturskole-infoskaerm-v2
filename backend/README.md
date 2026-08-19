# PlanIQ Display backend

Database schema changes are managed exclusively with Alembic.

- Render runs `python scripts/run_migrations.py` as `preDeployCommand`.
- The frozen production baseline is `20260712_30d_display_base`.
- Production is already registered at `20260712_30d_display_base`.
- Unknown revisions fail closed. An existing unstamped legacy database can only be adopted when `MIGRATION_ADOPT_VERIFIED_BASELINE=true`, after an exact frozen-baseline catalog verification. Reset the flag after the successful one-time deploy.
- Application startup must never execute DDL or `metadata.create_all()`.

Local migration validation:

```bash
cd backend
python scripts/validate_display_baseline.py
alembic history
alembic heads
```

## Backend-/API-oprydningskontrakt

Klientgodkendelse, organisationsændringer og enrollment-claim gemmer domæneændring,
kalender/token-state og audit-log i samme databasetransaktion. Enrollment-claim låser
den aktive installationskode med `SELECT ... FOR UPDATE`, så samme kode ikke kan
bruges samtidigt af flere klienter.

Den kanoniske HLS-reset-rute er `POST /api/hls/{client_id}/reset`. De tidligere
placeholder-ruter under `/api/clients/{id}/stream`, `/terminal` og
`/remote-desktop` samt de dublerede `/reset-hls` og `/stop-hls` er fjernet.
Frontend og kontrakttests må kun bruge den kanoniske rute.

CI kører hele Ruff `F`-familien, så både undefined names og ubrugte imports bliver
afvist. Administrative klient-, organisations- og enrollmenthandlinger skal have
auditering i samme commit som ændringen.
