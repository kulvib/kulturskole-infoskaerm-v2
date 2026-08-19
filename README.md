# PlanIQ Display / ClientFlow

Dette repository indeholder PlanIQ Display-webapplikationen og ClientFlow-runtime/integrationerne til fysiske infoskærmsklienter.

Projektet består af en fælles webplatform med backend, frontend, database-migrationer, ClientFlow release-/installationsmateriale og domænespecifik funktionalitet til blandt andet Livestream, Terminal og Remote Desktop.

## Repository-struktur

```text
.
├── backend/                     FastAPI-backend, Alembic-migrationer og backend-tests
├── frontend/                    React/Vite-frontend og frontend-tests
├── client-release/              ClientFlow releaseartefakter
├── clientflow-autoinstall-site/ Installations- og update-materiale til ClientFlow
├── scripts/                     Repository-/release-/valideringsscripts
├── render.yaml                  Render deployment-konfiguration
└── *.md                         Drift, release, audit og integrationsdokumentation
```

## Backend

Backenden ligger i `backend/` og kører som en FastAPI-applikation.

Databaseændringer håndteres med Alembic. Produktionsdeployet kører migrationer via:

```bash
cd backend
python scripts/run_migrations.py
```

Lokal kontrol af migrationer kan blandt andet køres med:

```bash
cd backend
python scripts/validate_display_baseline.py
alembic history
alembic heads
```

Applikations-startup må ikke oprette eller ændre databaseskemaet implicit.

## Frontend

Frontend ligger i `frontend/` og er bygget med React/Vite.

Typisk lokal installation og build:

```bash
cd frontend
npm ci
npm run build
```

Frontend deployes som statisk site og kommunikerer med backend over HTTPS/WSS.

## ClientFlow-domæner

ClientFlow omfatter flere funktionelle domæner, herunder:

- **Livestream** – skærm-capture og HLS-streaming.
- **Bruger-terminal / Admin-terminal** – interaktive PTY-sessioner på klienten.
- **Remote Desktop** – fjernvisning og fjernstyring.

Domænerne skal behandles som selvstændige sikkerheds- og driftsområder. Ændringer i ét domæne må ikke antages at være risikofrie for de andre uden dokumenteret isolation og fysisk test.

### Terminal

Terminal-v2 har egne Terminal-specifikke session-, event-, grant-, credential- og statusmodeller i backendens database.

Admin-terminalen anvender separat root-grant-validering på den fysiske klient. Bruger-terminal og Admin-terminal deler Terminal-domænet, men skal ikke dele credential-/session-state med Livestream eller Remote Desktop.

### Livestream

Livestream har særskilt ClientFlow capture-/upload-flow og tilhørende backend-ruter og state. Se blandt andet:

- `LIVESTREAM_V2_INTEGRATION.md`
- `LIVESTREAM_V2_ISOLATION_REPORT.txt`
- `LIVESTREAM_V2_CHANGED_FILES.txt`

### Remote Desktop

Remote Desktop ligger som et separat funktionelt domæne i backend/frontend og ClientFlow-runtime. Ændringer bør testes isoleret fra Terminal og Livestream.

## Deployment

`render.yaml` beskriver den nuværende Render-deployment:

- `infoskaerm-backend` – Python/FastAPI backend
- `infoskaerm-frontend` – statisk frontend

Backenden kører med én Uvicorn-worker i den nuværende deployment-konfiguration.

Secrets, database-credentials og signing keys skal leveres som environment variables på deployment-platformen og må ikke hardcodes i repositoryet.

## Database

Produktionsdatabasen konfigureres via `DATABASE_URL`.

Alembic er autoritativ for databaseskemaet. Nye tabeller, constraints, indexes og ændringer skal tilføjes gennem migrationer og valideres mod den aktuelle migrations-head før deployment.

Domænespecifikke data bør have domænespecifikke tabeller og credentials frem for generiske cross-domain records, når isolation er et krav.

## Tests og validering

Repositoryet indeholder backend-, frontend- og repository-kontrakttests.

Relevante kontroller ligger blandt andet i:

```text
backend/tests/
frontend/tests/
scripts/tests/
```

Før release bør de relevante domænetests køres sammen med repositoryets release-/readiness-kontroller.

## ClientFlow releases

ClientFlow release- og signing-flow er dokumenteret i:

- `CLIENTFLOW_RELEASE_PROCEDURE.md`
- `CLIENTFLOW_RELEASE_SIGNING.md`
- `FINAL_RELEASE_BASELINE.md`
- `RELEASE_CHECKLIST.md`

Releasefiler og runtime-identitet skal valideres efter projektets signing- og manifestkontrakter.

## Drift og fejlsøgning

Driftsvejledning findes i:

- `DRIFTSVEJLEDNING.md`
- `FINAL_AUDIT.md`
- `WEBSOCKET_PROTOCOL.md`
- `DEPENDENCY_MAINTENANCE.md`

Ved fejlsøgning på ClientFlow bør den fysiske Ubuntu-klient betragtes som autoritativ for faktisk runtime-adfærd. Undgå samtidige ændringer på tværs af Livestream, Terminal og Remote Desktop, medmindre en fælles afhængighed er dokumenteret som årsag.

## Sikkerhed

- Commit aldrig passwords, API-nøgler, database-URLs eller signing secrets.
- Brug environment variables til production secrets.
- Terminal root-grants og andre kortlivede credentials skal valideres efter deres specifikke issuer/audience/key-kontrakter.
- Administrative funktioner skal være beskyttet af relevante rolle-, token-version- og step-up-kontroller.
- Database- og credential-isolation skal verificeres med tests og ikke kun antages ud fra fil-/modulnavne.

## Projektstatus

Dette repository er under aktiv isolering og fejlsøgning af ClientFlow-domænerne. Funktionel godkendelse af et domæne er ikke i sig selv dokumentation for fuld infrastrukturel isolation fra de øvrige domæner.
