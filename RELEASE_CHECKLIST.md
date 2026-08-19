# PlanIQ Display – production-releasecheckliste

Denne checkliste bruges ved alle direkte production-deploys. CI ændrer ikke databasen og deployer ikke automatisk.

## Før commit

- Commit kun de filer, der faktisk skal ændres.
- Kontrollér, at `.env`, credentials, tokens, database-URL'er og andre secrets ikke er med.
- Fjern `__pycache__`, `*.pyc`, `node_modules` og `dist`.
- Ved schemaændringer: Tilføj en ny, immutable Alembic-revision fra aktuelt head, og opdatér schema-kontrakten i samme commit.
- Brug aldrig `create_all()`, startup-DDL eller blind `alembic stamp`. En ustemplet legacy-database må kun adopteres af den kontrollerede runner med fuld baseline-verifikation og det midlertidige flag `MIGRATION_ADOPT_VERIFIED_BASELINE=true`.

## GitHub Actions

Følgende checks skal være grønne før production-deploy:

- **Backend og databasekontrakt:** Dependency-installation, `pip check`, repository-kontrakt, Python-kompilering, Alembic-validering, offline migrations-SQL, FastAPI-import samt test af request-id, global fejlkontrakt, Alembic schema-readiness og HLS-preflight.
- **Frontend quality gate:** `npm ci`, `npm run lint`, frontend-kontrakttests og derefter `npm run build` med den committede `package-lock.json`.
- Dependabot-opdateringer må ikke auto-merges; changelog og CI-resultat gennemgås først.
- Repoet er privat på GitHub Free, så rulesets håndhæves ikke. Følg manuelt: `ny branch → pull request → grøn CI → merge til main → Render production`.
- Merge først, når både **Backend og databasekontrakt** samt **Frontend quality gate** er grønne; undgå direkte push til `main`, så Render ikke starter før CI er bestået.

## Før direkte production-deploy

- Kontrollér, at Render production peger på den forventede database og de korrekte domæner.
- Ved databaseændringer: Bekræft, at Neon restore/backup er tilgængelig før deploy.
- Gennemgå den genererede offline migrations-SQL, og bekræft, at den ikke indeholder utilsigtet data- eller schematab.
- Deploy kun en grøn commit fra standardbranchen.

## Efter deploy

- Render pre-deploy skal afslutte med forventet Alembic-revision før og efter.
- `/health` skal returnere HTTP 200.
- `/health/db` skal returnere HTTP 200 og dermed bekræfte både databaseforbindelse og præcis Alembic-head-status.
- Kontrollér, at begge health-responser har headeren `X-Request-ID`.
- Login som superadministrator og indlæs brugeradministration samt audit-log.
- Indlæs organisationer, installationskoder og kalender.
- Kontrollér at `/api/clients/` returnerer klienterne, og åbn Control Room.
- Kontrollér livestream/HLS samt adgang til terminal og Remote Desktop uden at ændre klientkonfiguration unødigt.

Ved HTTP 500/503 følges [`DRIFTSVEJLEDNING.md`](DRIFTSVEJLEDNING.md), og `request_id` bruges til at finde den tilsvarende Render-log.

## Rollback

- Ved applikationsfejl: Rollback til seneste fungerende Render-deploy.
- Ved databasefejl: Brug kun en eksplicit gennemgået Alembic-downgrade eller Neon restore.
- Brug aldrig manuel `alembic stamp` til at skjule en ukendt eller fejlet revision. Det midlertidige baseline-adoptionsflag må kun bruges, når databasen har ingen revision og matcher den frosne baseline præcist; nulstil flaget efter deploy.


## Dependency-integritet

- [ ] `python scripts/validate_dependency_contract.py` består.
- [ ] `python -m pip_audit --disable-pip --no-deps --progress-spinner off -r backend/requirements.lock.txt` består.
- [ ] `npm run audit:dependencies` består i `frontend/`.
- [ ] Runtimeversionerne matcher `DEPENDENCY_MAINTENANCE.md`.

## Production smoke test (Step 35D)

Efter Render-deploy og før releasen markeres færdig:

1. Bekræft i Render, at både backend og frontend står som live på den forventede commit.
2. Åbn GitHub Actions på `main`, vælg **Production smoke test**, og start workflowet manuelt.
3. Kræv grønt resultat for HTTPS-redirect, frontend-shell, to kald til `/health`, to kald til `/health/db` og fem unikke request-id'er.
4. Gennemfør derefter de eksisterende produktspecifikke kontroller: login, HLS/livestream, ClientFlow, WebSocket, terminal og Remote Desktop.
5. Ved fejl følges [`DRIFTSVEJLEDNING.md`](DRIFTSVEJLEDNING.md); workflowet deployer eller reparerer aldrig automatisk.

Lokal read-only kontrol:

```bash
python scripts/check_production_readiness.py --base-url https://display.planiq.dk --expected-product "PlanIQ Display" --expected-commit FULL_40_CHARACTER_GIT_SHA
```

Den almindelige CI kører kun smoke-værktøjets offline mocktests og må ikke kontakte
produktion. Production-workflowet bruger ingen secrets og kan kun gennemføres fra `main`.

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

- [ ] Bekræft, at `/release.json` returnerer `component: frontend` fra det fysisk byggede **statiske frontendartefakt**.
- [ ] Bekræft, at `/version` returnerer `component: backend` fra backendens `RENDER_GIT_COMMIT`.
- [ ] Kontrollér, at `render.yaml` ikke har en rewrite eller proxy for `/release.json`.
- [ ] Kør Production smoke test med den fulde Git SHA som `--expected-commit`; testen skal fejle, hvis enten frontend eller backend er på en anden commit.
- [ ] Ved mismatch: kontrollér begge Render-services separat. Omgå aldrig fejlen ved at lade backend levere frontend-identiteten.


## Auth abuse-protection og rate-limit-kontrakt (Step 37A)

- [ ] `python scripts/ci_validate_repository.py` er grøn.
- [ ] `python -m unittest backend/tests/test_rate_limit_contract.py` er grøn i backendens testmiljø.
- [ ] Backend starter med én worker, medmindre `REDIS_URL` er konfigureret og `RATE_LIMIT_REDIS_REQUIRED=true`.
- [ ] Login returnerer et fælles `429`-svar med `Retry-After`, `X-Request-ID`, `retry_after` og `error=rate_limit_exceeded`, når grænsen overskrides.
- [ ] Frontend viser serverens faktiske ventetid og starter ikke refresh-storme efter en `429`.
- [ ] Succesfuldt login nulstiller kontoens failed-login-bucket.
- [ ] Ingen rå emailadresser, passwords eller tokens indgår i limiter-storage keys eller rate-limit-loglinjer.
- [ ] De eksisterende produktspecifikke grænser og produktfunktioner er bevaret.

## Afsluttende harmoniseringsaudit (Step 38A)

- [ ] `python scripts/ci_validate_repository.py` er grøn.
- [ ] `cd backend && python -m unittest tests/test_jwt_contract.py -v` er grøn i backendens testmiljø.
- [ ] Render har de dokumenterede produktspecifikke værdier for `JWT_ISSUER` og `JWT_AUDIENCE`.
- [ ] Login, refresh og logout er testet efter deploy; gamle access-tokens må højst udløse automatisk refresh eller nyt login.
- [ ] Production smoke test er grøn efter både frontend- og backenddeploy.
- [ ] Ingen `STEP*_PATCH_MANIFEST.txt` eller gamle fase-/cleanup-noter er committed.
- [ ] Bekræft, at almindelig backend-start ikke opretter eller ændrer brugere.
- [ ] Test recovery-scriptet kun ved en dokumenteret nødsituation og kun når ingen aktiv administrator findes.

## ClientFlow signed release

- [ ] `clientflow_version_signed.json` has a strictly higher release_sequence for a new release.
- [ ] Installer SHA256 and size match the signed manifest.
- [ ] Manifest is signed with the offline private key; no private key/passphrase exists in the repo.
- [ ] `expected_clientflow_version.json` matches the signed legacy bridge manifest byte-for-byte.
- [ ] `python scripts/validate_clientflow_contract.py` passes.
- [ ] One physical ClientFlow smoke-test passes before broad rollout.


## Batch 7 – signed version catalog

- [ ] `clientflow_release_catalog_signed.json` verifies with the trusted public key.
- [ ] Backend catalog copy matches the autoinstall catalog byte-for-byte.
- [ ] `latest_stable` equals `default_install_version`.
- [ ] Every `stable`/`supported` installer matches catalog SHA256 and size.
- [ ] Blocked releases contain metadata only and no published installer.
- [ ] `clientflow_version.json` and the ClientFlow 1.1.8 installer are absent.
- [ ] `catalog_sequence` and each new `release_sequence` are higher and never reused.
- [ ] Control Room downgrade requires confirmation, reason and critical audit log.
- [ ] Factory selector defaults to latest stable and verifies signature/hash/size.
- [ ] One stable update and one supported rollback have been smoke-tested before broad rollout.
