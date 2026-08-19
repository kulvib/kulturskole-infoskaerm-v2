# PlanIQ Display – drifts- og fejlfindingsvejledning

Denne vejledning bruges ved production-fejl. Audit-loggen er fortsat kun til
bruger- og sikkerhedshændelser; systemfejl hører hjemme i Render-loggen.

## Health checks

- `/health` er liveness og skal returnere HTTP 200, selv hvis databasen er nede.
- `/health/db` er readiness og returnerer kun HTTP 200, når både databaseforbindelsen virker, repoet har ét Alembic-head, og `alembic_version` står præcist på dette head. Den ændrer aldrig databasen.
- `/health/db-pool` er en beskyttet superadministrator-diagnose og må ikke bruges som offentlig health check.
- Render skal fortsat bruge `/health` som `healthCheckPath`.

## Request-id og fejlrespons

Alle HTTP-svar, herunder HLS-preflight, har headeren `X-Request-ID`. Uventede fejl
returnerer en neutral JSON-respons med `error` og `request_id`, eksempelvis:

```json
{
  "detail": "En intern serverfejl opstod. Prøv igen senere.",
  "error": "internal_server_error",
  "request_id": "8e8c8c6c4b1942b8a3a44ff34b619c98"
}
```

Ved HTTP 500 eller 503:

1. Notér `request_id` fra responsen eller browserens Network-fane.
2. Åbn Display-backendservicen i Render og søg efter `request_id=<id>`.
3. Sammenhold tidspunkt, HTTP-metode, path, statuskode, fejltype og kodeplacering.
4. Kopiér aldrig access-token, refresh-cookie, klienttoken, password, request body, database-URL eller en komplet WebSocket-URL til en sag eller chat.

Den globale fejllogger gemmer ikke query strings, headers, cookies, request bodies
eller rå exceptiontekster. Den logger kun fejltype og en dataminimeret kodeplacering.

## Audit-log og request-korrelation

Audit-loggen gemmes i databasen og må ikke kopieres til Render-systemloggen som
separate `AUDIT:`-linjer. Nye auditposter gemmer det validerede `request_id`, når
hændelsen sker i en HTTP-request. I audit-detaljer og CSV kan samme id derfor
sammenholdes med `request_id=<id>` i Render-loggen.

Audit-API'et returnerer `Cache-Control: no-store`, serialiserer UTC-tidspunkter
med `Z` og filtrerer bruger-/objekthistorik server-side på både `entity_type` og
`entity_id`. Retentionperioden læses fra backend og må ikke hardcodes i UI'et.

Ved deploy af Step 34A skal Alembic-revision
`20260712_34a_audit_request_id` være kørt før den nye applikationsversion tager
trafik. Render udfører dette gennem `preDeployCommand`. Efter deploy kontrolleres:

1. `/health` og `/health/db` returnerer HTTP 200.
2. En ufarlig audit-hændelse vises med dansk lokaltid i UI'et.
3. Audit-API'ets rå `created_at` slutter med `Z`.
4. Den nye hændelse har et request-id, som kan findes i Render-loggen.
5. Audit-responsen har `Cache-Control: no-store`.

## Statuskoder

- `401`: Session eller klientautentificering mangler eller er udløbet.
- `403`: Principal mangler rettighed, eller Origin-kontrollen afviser requesten.
- `404`: Endpoint, klient, HLS-stream eller fil findes ikke. En HLS-404 kan være forventet efter streamstop.
- `409`: Forretningskonflikt, eksempelvis dublet eller tilstand der ikke tillader handlingen.
- `422`: Valideringsfejl i input.
- `500 internal_server_error`: Uventet applikationsfejl. Søg på request-id.
- `503 database_unavailable`: Database/pool er midlertidigt utilgængelig. Kontrollér Neon og Render.
- `503 database_schema_not_ready`: Databasen svarer, men Alembic-status mangler eller afviger fra den kørende release.

## Databasefejl

Ved `503 database_unavailable`:

1. Kontrollér `/health` og `/health/db` separat.
2. Kontrollér Neon-status og om production-databasen er tilgængelig.
3. Kontrollér Render-loggen for `database_pool_timeout` eller `database_health_check_failed`.
4. Brug kun `/health/db-pool` som indlogget superadministrator, når poolstatus konkret skal undersøges.
5. Kontrollér pool-env uden at udskrive `DATABASE_URL`.
6. Brug ikke en manuel/blind `alembic stamp`, startup-DDL eller `create_all()` som fejlløsning. For en eksisterende ustemplet Display-database bruges kun runnerens kontrollerede engangs-adoption med `MIGRATION_ADOPT_VERIFIED_BASELINE=true`; flaget nulstilles straks efter en vellykket deploy.

## Schema-readiness

Ved `503 database_schema_not_ready`:

1. Find `request_id` i responsen og søg efter `database_schema_not_ready` i Render-loggen.
2. Brug den neutrale `reason` i loggen til at skelne mellem manglende/tom `alembic_version`, gammel eller ukendt revision samt flere database- eller repo-heads. Revision-id'er returneres ikke til klienten og logges ikke af health-endpointet.
3. Kontrollér pre-deploy-loggen fra `python scripts/run_migrations.py` og sammenhold den med repoets `alembic heads`.
4. Kør ikke manuel `stamp`, startup-DDL eller en skjult migration. Stop deploy/rollback og foretag en ny kode- og schemaanalyse eller en kontrolleret Neon-restore.
5. `/health` skal fortsat være HTTP 200, så en schemaafvigelse ikke gør Render-liveness databaseafhængig.

## Engangs-adoption af eksisterende Display-database

Brug kun denne procedure, når pre-deploy stopper med beskeden om eksisterende Display-tabeller uden Alembic-revision:

1. Sæt Render-variablen `MIGRATION_ADOPT_VERIFIED_BASELINE=true` på Display-backenden.
2. Deploy samme gennemgåede commit igen. Runneren sammenligner alle tabeller, kolonner, constraints, indexes, sequences, triggers og extensions med den frosne baseline, før baseline registreres.
3. Bekræft i pre-deploy-loggen `verificeret baseline adopteret: ja` og revision `20260712_34a_audit_request_id`.
4. Nulstil eller fjern `MIGRATION_ADOPT_VERIFIED_BASELINE` og deploy igen. Den efterfølgende log skal vise `verificeret baseline adopteret: nej`.
5. Ved en schema-afvigelse stoppes deployment; ret ikke databasen og brug ikke manuel stamp uden en ny kode-/schemaanalyse.

## Display-specifik kontrol

Efter en fejl eller rollback kontrolleres mindst:

- login, refresh-session, brugeradministration og audit-log
- organisationer, installationskoder og kalender
- `/api/clients/` og klientdetaljer
- Control Room og klientstatus
- livestream/HLS, herunder start ved to segmenter og viewer-timeout på 180 sekunder
- terminal og Remote Desktop uden at ændre klientkonfiguration unødigt

Forventede HLS-forhold som manglende manifest før streamstart, stop-marker efter
sidste viewer eller kortvarigt segmentgab skal ikke automatisk behandles som en
global backendfejl. Kontrollér først Control Room-status og den konkrete HTTP-status.

## Rollback

- Applikationsfejl uden schemaændring: rollback til seneste fungerende Render-deploy.
- Fejl efter schemaændring: gennemgå Alembic-revision og offline SQL; brug kun en eksplicit gennemgået downgrade eller Neon restore.
- Efter rollback: kontrollér `/health`, `/health/db` og de Display-specifikke funktioner ovenfor.

## GitHub Free-procedure

De private repositories bruger GitHub Free, så rulesets håndhæves ikke. Følg derfor altid manuelt:

```text
ny branch → pull request → grøn CI → merge til main → Render production
```

Kontrollér både **Backend og databasekontrakt** og **Frontend build** før merge.


## Runtime og dependencies

Se [DEPENDENCY_MAINTENANCE.md](DEPENDENCY_MAINTENANCE.md) for fastlåste runtimeversioner, lockfiler, audit og opdateringsprocedure.

## Production smoke test (Step 35D)

Kør først workflowet **Production smoke test**, når både backend- og
frontend-servicen står som live i Render. Workflowet kan kun gennemføres fra
`main`, bruger ingen secrets og ændrer hverken applikation, database eller Render.

Lokal diagnostik:

```bash
python scripts/check_production_readiness.py --base-url https://display.planiq.dk --expected-product "PlanIQ Display" --expected-commit FULL_40_CHARACTER_GIT_SHA
```

Kontrollen kræver HTTP-til-HTTPS-redirect, korrekt frontend-title, præcis
`{"status":"ok"}` fra både `/health` og `/health/db` samt fem forskellige
`X-Request-ID`-headers. HTTP 429/500/502/503/504 og netværksfejl genprøves tre
gange med fem sekunders mellemrum. Hvis et kald først består efter retry, fremgår
det af loggen og bør sammenholdes med Render- og Neon-status.

Ved vedvarende fejl:

1. Brug endpoint, statuskode og eventuelt request-id fra workflowloggen.
2. Kontrollér det tilsvarende tidspunkt i Render uden at kopiere secrets eller bodies.
3. Ved `/health/db` følges afsnittene om database- og schema-readiness.
4. Ved frontend- eller redirectfejl kontrolleres custom domain, TLS og static-service.
5. Rollback ved en reel releasefejl; omgå aldrig kontrollen med `stamp` eller startup-DDL.

Smoke-testen supplerer, men erstatter ikke manuel kontrol af login, HLS/livestream, ClientFlow, WebSocket, terminal og Remote Desktop.

## Releaseidentitet og commit-sporbarhed (Step 36A)

Render leverer automatisk den fulde deployment-commit i `RENDER_GIT_COMMIT`.
Frontenden skriver den samme commit til `/release.json` under build, og backendens
read-only `/version`-endpoint returnerer produkt, komponent og commit uden databasekald.
Begge endpoints bruger `Cache-Control: no-store`; `/version` har desuden `X-Request-ID`.

Efter merge og afsluttet Render-deploy køres **Production smoke test** fra `main`.
Workflowet sender `${{ github.sha }}` som `--expected-commit` og fejler, hvis
frontend, backend og den forventede GitHub-commit ikke er identiske. Det kræver ingen
Render API-token eller andre secrets. Lokal read-only kontrol:

```bash
python scripts/check_production_readiness.py --base-url https://display.planiq.dk --expected-product "PlanIQ Display" --expected-commit FULL_40_CHARACTER_GIT_SHA
```

Ved mismatch kontrolleres først, at begge Render-services er færdigdeployed på samme
commit. Kør derefter workflowet igen. Rollback til seneste fungerende deployment ved
en reel releasefejl. Commitkontrollen supplerer, men erstatter ikke manuel kontrol af
login, HLS/livestream, ClientFlow, WebSocket, terminal og Remote Desktop.

## Runtime- og dependency-kontrakt (Step 36B)

Projektet bruger Python `3.13.14`, Node.js `22.22.0`, npm `10.9.4` og pip `26.1.2`. Python installeres fra hash-låste lockfiler med `--require-hashes`; frontend installeres med `npm ci`. CI kører `pip check`, `pip-audit`, npm-audit, dependency-runtime-tests og `scripts/validate_dependency_contract.py`.

Vedligeholdelsesproceduren står i [DEPENDENCY_MAINTENANCE.md](DEPENDENCY_MAINTENANCE.md).

## Uafhængig frontend/backend deploy-provenance (Step 36C)

`/release.json` skal være det fysisk byggede **statiske frontendartefakt** fra Render Static Site. Det må ikke være en rewrite til backend. `/version` kommer separat fra backend og bruger backend-servicens `RENDER_GIT_COMMIT`.

Ved commit-mismatch:

1. Hent `/release.json` og `/version` separat uden browsercache.
2. Sammenhold begge fulde SHA-værdier med den commit, der blev sendt som `--expected-commit`.
3. Hvis kun frontend afviger, kontrollér Static Site-build og deploy. Hvis kun backend afviger, kontrollér backend-deployet.
4. Kør først Production smoke test igen, når begge services står live på samme forventede commit.
5. Rollback den afvigende service ved en reel releasefejl; opret aldrig et backend-endpoint, der syntetiserer frontend-identiteten.


## Auth abuse-protection og rate-limit-drift (Step 37A)

Standarddriften bruger én Uvicorn-worker og in-memory limiter-state. Følgende miljøvariabler styrer storagekontrakten:

- `REDIS_URL`: tom ved én worker/én instans; ellers URL til en Redis/Valkey-kompatibel delt store
- `RATE_LIMIT_NAMESPACE`: produktspecifikt namespace, så buckets ikke deles mellem PlanIQ-produkter
- `RATE_LIMIT_REDIS_REQUIRED`: `false` ved fallback; skal være `true`, når delt storage er et skaleringskrav
- `RATE_LIMIT_MEMORY_MAX_KEYS`: maksimal størrelse på in-memory fallback (standard `10000`)

Ved planlagt skalering:

1. Opret/tilslut en delt Redis/Valkey-kompatibel store.
2. Sæt `REDIS_URL` som secret på backendservicen.
3. Sæt `RATE_LIMIT_REDIS_REQUIRED=true`.
4. Deploy og bekræft loglinjen `rate_limit_storage=redis`.
5. Kontrollér et testet `429`-svar for `Retry-After`, `X-Request-ID`, `retry_after` og `error=rate_limit_exceeded`.
6. Først derefter må worker- eller instansantallet øges.

Hvis Redis er påkrævet, men utilgængelig ved opstart, skal backend fejle i stedet for lydløst at splitte tællere. Rate-limit-logs indeholder bucket og request-ID, men ikke rå emailadresser, passwords, tokens eller de hash-baserede storage keys.

De eksisterende Display-grænser er bevaret, inklusive særskilte buckets for browserlogin, ClientFlow `client-token` og enrollment. HLS, livestream, Remote Desktop og terminal er ikke ændret.

## JWT- og recovery-drift (Step 38A)

`JWT_ISSUER` og `JWT_AUDIENCE` er eksplicitte, ikke-hemmelige Render-variabler.
De må ikke genbruges på tværs af PlanIQ-produkterne. Access-tokens kræver `exp`,
`iat`, `nbf`, `jti`, `iss` og `aud`; ændring af issuer/audience invaliderer straks
ældre access-tokens, mens opaque refresh-tokens og databaseindhold er uændret.

Ved 401 umiddelbart efter deploy kontrolleres først, om frontenden gennemfører den
normale refresh. Ved vedvarende fejl logges brugeren ind igen. Slæk aldrig på
claim-valideringen for at acceptere ældre tokens.

Display opretter ikke længere en superadministrator automatisk ved backend-start.
Ved en dokumenteret recovery-situation, hvor databasen ikke har en aktiv admin eller
superadmin, sættes `ADMIN_PASSWORD` midlertidigt i den lokale shell/Render Shell og
følgende kommando køres manuelt fra `backend`:

```bash
python scripts/bootstrap_superadmin.py --username RECOVERY_USER --email RECOVERY_EMAIL --confirm-create
```

Kommandoen afviser oprettelse, hvis en aktiv administrator findes, eller hvis
brugernavn/email allerede er i brug. Den nye konto får tvunget passwordskift.
Fjern `ADMIN_PASSWORD` fra miljøet straks efter brug. Kommandoen må aldrig tilføjes
til Render start- eller pre-deploy-command.

## ClientFlow versionsvalg og rollback

- Installér fra hele `clientflow-autoinstall-site`-mappen med `CLIENTFLOW_START_HER.sh`.
- Standard er `latest_stable`; en `supported` release kan vælges eksplicit.
- `blocked` og `deprecated` releases må ikke installeres.
- Control Room kræver bekræftelse og begrundelse ved downgrade og skriver en kritisk audit-log.
- Deploymentsekvensen må aldrig sænkes eller genbruges.
- Katalog, backendkopi og installerfiler skal deployes i samme commit.
