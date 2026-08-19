# ClientFlow – komplet release-, installations- og rollbackprocedure

Denne vejledning er den kanoniske arbejdsgang for alle fremtidige ClientFlow-releases i PlanIQ Display.

Den dækker hele forløbet fra en ny ClientFlow-version er klar, til filerne er uploadet til GitHub, CI er grøn, autoinstall-sitet og PlanIQ Display er deployet, og versionen er smoke-testet på en fysisk klient.

Vejledningen gælder både:

- nye factory-installationer via `clientflow-autoinstall-site`;
- opdatering af eksisterende klienter gennem Control Room;
- kontrolleret manuel downgrade;
- automatisk teknisk rollback efter en mislykket installation;
- akut blokering af en fejlbehæftet release.

---

## 1. Nuværende autoritative releasekontrakt

Følgende filer udgør den autoritative releasekæde:

```text
clientflow-autoinstall-site/clientflow_release_catalog_signed.json
backend/service1/clientflow_release_catalog_signed.json
clientflow-autoinstall-site/clientflow_update_pubkey.pem
```

Kataloget i backend og kataloget på autoinstall-sitet skal være **byte-identiske**.

Mens legacy-klienter fortsat bruger schema-2-broen, bevares også denne signerede fremadrettede bro:

```text
clientflow-autoinstall-site/clientflow_version_signed.json
clientflow-autoinstall-site/expected_clientflow_version.json
```

De to bridge-filer skal være byte-identiske og altid pege på den aktuelle `latest_stable`.

Det gamle usignerede manifest må aldrig genindføres:

```text
clientflow-autoinstall-site/clientflow_version.json
```

### Aktuel baseline ved oprettelsen af denne vejledning

```text
Latest stable:       1.1.18
Deprecated identity:  1.1.12
Supported predecessor: 1.1.15
Deprecated pilot:     1.1.16
Historical 24.04:    1.1.11
Blocked history:     1.1.8
Catalog sequence:    1117
Signing key ID:      c159120d1a1784f6
```

Baselineværdierne er kun reference. Ved hver ny release er det det signerede katalog og `FINAL_RELEASE_BASELINE.md`, der er source of truth.

---

## 2. De fire numre må ikke blandes sammen

### Softwareversion

Eksempel:

```text
1.1.11
```

Dette er den ClientFlow-version, der installeres.

### Release sequence

Eksempel:

```text
1111
```

`release_sequence` identificerer ét uforanderligt releaseartefakt. En ny release skal altid have et højere, aldrig tidligere anvendt nummer.

En eksisterende version beholder sin oprindelige `release_sequence`, selv hvis den senere igen markeres som `stable`.

### Catalog sequence

Eksempel:

```text
1111
```

`catalog_sequence` identificerer generationen af det signerede versionskatalog. Den skal stige ved **enhver** ændring af kataloget, også når:

- en version blokeres;
- en tidligere version igen bliver seneste stabile;
- kompatibilitetsregler ændres;
- en version går fra `supported` til `deprecated`.

### Deployment sequence

`deployment_sequence` oprettes af backend pr. klient og stiger ved hver update- eller downgradeordre.

Eksempel:

```text
Deployment 24: installér 1.1.12
Deployment 25: autoriseret downgrade til 1.1.11
```

Softwareversionen kan gå tilbage. Deploymentsekvensen må aldrig gå tilbage eller genbruges.

---

## 3. Release-status og retention

Hver katalogpost har én status:

| Status | Ny installation | Update | Manuel rollback | Betydning |
|---|---:|---:|---:|---|
| `stable` | Ja | Ja | Ja | Seneste anbefalede version og standardvalg |
| `supported` | Ja | Ja | Ja, hvis tilladt | Understøttet tidligere version |
| `deprecated` | Nej | Nej | Nej | Kendt historik, men ikke længere valgfri |
| `blocked` | Nej | Nej | Nej | Sikkerheds- eller kompatibilitetsblokeret |

Standardpolitikken er højst tre installérbare versioner, men en version med en sikkerhedsfejl skal blokeres straks uanset alder.

Blokerede versioners metadata bevares i kataloget, men installerfilen fjernes fra autoinstall-sitet.

---

## 4. Absolutte regler

Disse regler må aldrig fraviges:

1. En eksisterende versionsbestemt installerfil må aldrig overskrives.
2. En tidligere anvendt `release_sequence` eller `catalog_sequence` må aldrig genbruges.
3. Den private signeringsnøgle eller passphrase må aldrig uploades til GitHub, Render, autoinstall-sitet eller en klient.
4. Kun den offentlige nøgle må ligge i repoet.
5. Kataloget skal signeres efter den sidste indholdsændring.
6. `SHA256SUMS.txt` skal genereres efter den sidste signering og efter alle øvrige filændringer.
7. Backendkataloget og autoinstall-kataloget skal være byte-identiske.
8. En `blocked` eller `deprecated` version må ikke have `installable: true` eller `update_allowed: true`.
9. Root-services skal fortsat bruge root-ejet kode og runtime:

```text
/opt/clientflow/venv
/usr/local/lib/clientflow-root
```

10. Root-services må aldrig eksekvere kode eller interpreter fra den skrivbare mappe:

```text
/opt/clientflow/api
```

11. Factory-pakken må ikke indeholde credentials eller state fra en tidligere klient.
12. Nye installationer skal som standard vælge `latest_stable`.
13. En manuel downgrade skal kræve superadministrator, bekræftelse, begrundelse og kritisk audit-log.
14. Production deployes kun fra en pull request med grøn CI.
15. En ny release rulles først ud til én fysisk testklient.

---

# DEL A – Forbered den nye release

## 5. Start altid fra den aktuelle produktion

Inden arbejdet starter:

- download eller upload et helt frisk repo fra den commit, der faktisk kører i produktion;
- kontrollér, at seneste deployment, CI og smoke test er grønne;
- kontrollér den nuværende baseline i:

```text
FINAL_RELEASE_BASELINE.md
clientflow-autoinstall-site/clientflow_release_catalog_signed.json
```

Brug aldrig en gammel lokal arbejdskopi som releasegrundlag.

### Ved arbejde gennem ChatGPT

Upload det helt friske repo og beskriv den ønskede ClientFlow-ændring.

Den private signeringsnøgle og passphrase skal fortsat opbevares separat og må ikke lægges i repo-pakken. Den endelige release er først godkendt, når den signerede katalogfil og alle checksums er verificeret.

---

## 6. Fastlæg releaseidentiteten

For en ny version, eksempelvis 1.1.11, fastlægges:

```text
version:               1.1.11
client_version:        1.1.11
client_version_patch:  v1.1.11_<kort_beskrivelse>
revision:              release_v1_1_11_<kort_beskrivelse>
release_sequence:      1111
catalog_sequence:      1111 eller højere
status:                stable
```

Brug et versionsbestemt filnavn:

```text
clientflow_clean_ubuntu_installer_v1_1_11.zip
```

### Statusændring ved normal release

Ved en almindelig ny stabil release vil kataloget typisk ændres sådan:

```text
1.1.15  stable
1.1.14  deprecated
1.1.12  deprecated
1.1.11  supported
1.1.10  supported
1.1.9   deprecated
1.1.8   blocked
```

Den ældste version gøres kun `deprecated`, når den ikke længere skal kunne installeres eller bruges til rollback.

---

## 7. Definér kompatibiliteten før build

Hver releasepost skal mindst tage stilling til:

```text
min_current_version
max_current_version
ubuntu_versions
rollback_allowed
installable
update_allowed
requires_explicit_downgrade
requires_reboot
```

Eksempel for en ny stabil version:

```json
{
  "version": "1.1.11",
  "release_sequence": 1111,
  "status": "stable",
  "installable": true,
  "update_allowed": true,
  "rollback_allowed": true,
  "requires_explicit_downgrade": false,
  "requires_reboot": false,
  "min_current_version": "1.1.9",
  "max_current_version": null,
  "ubuntu_versions": ["24.04"]
}
```

Hvis ClientFlow-protokollen ændres, skal backend og frontend fortsat være kompatible med alle versioner, der står som `stable` eller `supported`.

### Release med backend- eller frontendafhængighed

Hvis den nye ClientFlow-version kræver ændringer i backend, frontend, database eller WebSocket-protokol, anvendes to faser:

#### Fase A – kompatibilitetsdeploy

1. Deploy backend/frontend, der understøtter både den nuværende og den kommende ClientFlow-version.
2. Publicér endnu ikke den nye installer som `stable` eller `supported`.
3. Kør CI, production smoke test og relevante protokoltests.

#### Fase B – ClientFlow-publicering

1. Tilføj installer og signeret katalog.
2. Gør den nye version til `stable`.
3. Deploy autoinstall-site og backendkatalog.
4. Test én fysisk klient.

Det forhindrer, at en klient kan hente en ny version, før serveren er klar.

---

## 8. Byg et uforanderligt installerartefakt

Den nye ZIP skal indeholde den komplette factory-installer og payload.

Kontrollér blandt andet:

- neutral factory-state;
- ingen client ID, client secret, enrollment code eller andre credentials;
- ingen privat signeringsnøgle;
- præcise, låste ClientFlow-dependencies;
- korrekt root-runtime-boundary;
- ZIP- og TAR-paths uden traversal;
- ingen usikre symlinks eller specialfiler;
- shell-syntax og Python compile;
- rollback af kode, venv og konfiguration ved installerfejl;
- byte-for-byte konsistent releaseidentitet mellem katalog, factory-script, self-update-script og payloadens autoritative versionsfiler.

CI skal læse releaseidentiteten direkte fra det færdige ZIP/TAR-artefakt og sammenligne `version`, `client_version_patch`, `revision` og `release_sequence` med katalogposten. Det er ikke tilstrækkeligt kun at validere build-scriptets standardværdier.

Installerartefaktet må ikke ændres efter publicering. Hvis der opdages en fejl, oprettes en ny version med nyt filnavn og ny `release_sequence`.

---

## 9. Beregn hashes og størrelse

Beregn mindst:

- installerens SHA256;
- installerens størrelse i bytes;
- payloadens SHA256.

Portabel kontrol med Python:

```bash
python - <<'PY'
from hashlib import sha256
from pathlib import Path

path = Path("clientflow-autoinstall-site/clientflow_clean_ubuntu_installer_v1_1_11.zip")
print("size:", path.stat().st_size)
print("sha256:", sha256(path.read_bytes()).hexdigest())
PY
```

Payloaden kan kontrolleres direkte fra ZIP-filen:

```bash
unzip -p \
  clientflow-autoinstall-site/clientflow_clean_ubuntu_installer_v1_1_11.zip \
  payload_clientflow_v1_0_0.tar.gz \
  | shasum -a 256
```

Indsæt de endelige værdier i den nye katalogpost.

---

# DEL B – Opdatér og signér versionskataloget

## 10. Opdatér releasekataloget

Redigér:

```text
clientflow-autoinstall-site/clientflow_release_catalog_signed.json
```

Før signering:

1. fjern eller erstat den gamle `signature`;
2. øg `catalog_sequence`;
3. opdatér `latest_stable`;
4. opdatér `default_install_version`;
5. tilføj den nye releasepost;
6. opdatér statussen på tidligere releases;
7. kontrollér retentionpolitikken;
8. kontrollér at alle installérbare releases har en fysisk installerfil;
9. kontrollér at blokerede releases ikke har en installerfil på sitet.

`latest_stable` og `default_install_version` skal normalt være ens.

---

## 11. Opdatér 1.1.9-bridge-manifestet

Så længe legacy-klienter fortsat bruger schema-2-broen, skal denne fil opdateres til den nye stabile version:

```text
clientflow-autoinstall-site/clientflow_version_signed.json
```

Den skal fortsat være schema 2 / `stable-signed` og pege frem til:

```text
clientflow_release_catalog_signed.json
```

Efter signering kopieres den byte-for-byte til:

```text
clientflow-autoinstall-site/expected_clientflow_version.json
```

Bridge-filerne kan først udfases, når:

- 1.1.9 ikke længere kan installeres;
- ingen aktive klienter kører 1.1.9;
- katalog og klientkode er opdateret til at kræve den nye model uden bridge.

---

## 12. Signér offline

Kør signeringen fra repoets rod i en kontrolleret lokal release-workspace:

```bash
python scripts/sign_clientflow_manifest.py \
  clientflow-autoinstall-site/clientflow_release_catalog_signed.json \
  --private-key /secure/path/clientflow_manifest_signing_private.pem \
  --public-key clientflow-autoinstall-site/clientflow_update_pubkey.pem \
  --passphrase-file /secure/path/clientflow_signing_key_passphrase.txt
```

Signér derefter bridge-manifestet, mens 1.1.9 er understøttet:

```bash
python scripts/sign_clientflow_manifest.py \
  clientflow-autoinstall-site/clientflow_version_signed.json \
  --private-key /secure/path/clientflow_manifest_signing_private.pem \
  --public-key clientflow-autoinstall-site/clientflow_update_pubkey.pem \
  --passphrase-file /secure/path/clientflow_signing_key_passphrase.txt
```

Kontrollér, at `signature_key_id` fortsat er den forventede offentlige key ID.

Kopiér derefter de signerede bytes:

```bash
cp \
  clientflow-autoinstall-site/clientflow_release_catalog_signed.json \
  backend/service1/clientflow_release_catalog_signed.json

cp \
  clientflow-autoinstall-site/clientflow_version_signed.json \
  clientflow-autoinstall-site/expected_clientflow_version.json
```

Kontrollér byte-identitet:

```bash
cmp \
  clientflow-autoinstall-site/clientflow_release_catalog_signed.json \
  backend/service1/clientflow_release_catalog_signed.json

cmp \
  clientflow-autoinstall-site/clientflow_version_signed.json \
  clientflow-autoinstall-site/expected_clientflow_version.json
```

Ingen output fra `cmp` betyder, at filerne matcher.

---

## 13. Regenerér SHA256SUMS til sidst

Dette trin udføres først, når alle filer i autoinstall-mappen har deres endelige bytes.

Fra repoets rod:

```bash
python - <<'PY'
from hashlib import sha256
from pathlib import Path

root = Path("clientflow-autoinstall-site")
files = sorted(
    path for path in root.iterdir()
    if path.is_file() and path.name != "SHA256SUMS.txt"
)

lines = []
for path in files:
    digest = sha256(path.read_bytes()).hexdigest()
    lines.append(f"{digest}  {path.name}")

(root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
```

Verificér:

```bash
cd clientflow-autoinstall-site
shasum -a 256 -c SHA256SUMS.txt
cd ..
```

Alle linjer skal ende med `OK`.

Hvis en fil ændres eller signeres igen, skal `SHA256SUMS.txt` genereres igen.

---

## 14. Opdatér dokumentationen

Ved hver release opdateres mindst:

```text
FINAL_RELEASE_BASELINE.md
CLIENTFLOW_RELEASE_SIGNING.md
clientflow-autoinstall-site/README_INSTALLATIONSFLOW_v1_0_0.md
clientflow-autoinstall-site/README_v1_0_0_clean_installer.md
```

Opdatér også `README.md`, `DRIFTSVEJLEDNING.md` eller `RELEASE_CHECKLIST.md`, hvis releaseprocessen eller kontrakterne ændres.

`clientflow-autoinstall-site/index.html` læser normalt versionslisten dynamisk fra kataloget og behøver derfor ikke en versionsændring, medmindre selve brugeroplevelsen eller katalogkontrakten ændres.

---

# DEL C – Lokal og automatisk validering

## 15. Kør ClientFlow- og repositorykontroller

Fra repoets rod:

```bash
python scripts/ci_validate_repository.py
python scripts/validate_dependency_contract.py
python scripts/validate_clientflow_contract.py
python -m ruff check backend/service1 backend/scripts scripts --select F
python -m compileall -q backend/service1 backend/tests backend/scripts backend/migrations
```

Kør backendtests:

```bash
cd backend
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/validate_display_baseline.py
alembic heads
alembic history
alembic upgrade head --sql > /tmp/planiq-migration.sql
test -s /tmp/planiq-migration.sql
cd ..
```

Kør production-readiness-værktøjets offline-tests:

```bash
python -m unittest discover -s scripts/tests -p "test_*.py" -v
```

---

## 16. Kør frontendkontroller

Projektets låste versioner er:

```text
Node.js 22.22.0
npm 10.9.4
```

Kør:

```bash
cd frontend
npm ci
npm run audit:dependencies
npm run test:dependency-runtime
npm run lint
npm run test:runtime-status
npm run test:bundle-budget
npm run test:api-error
npm run test:backend-cleanup
npm run test:calendar-auth-client
npm run test:remote-desktop-urls
npm run test:clientflow-version-catalog
npm run test:release-metadata
GITHUB_SHA=0000000000000000000000000000000000000000 npm run build
cd ..
```

Krav:

- 0 ESLint-fejl;
- 0 ESLint-advarsler;
- 0 dependency-auditfund eller en eksplicit, godkendt allowlist;
- alle kontrakttests grønne;
- production-build grøn;
- bundle-budget grønt.

---

## 17. Kontrollér releasepakken manuelt

Inden GitHub-upload:

- åbn ZIP-listen og kontrollér filnavne og mappestruktur;
- kontrollér, at ingen `.env`, credentials, private keys eller passphrasefiler er med;
- kontrollér, at den nye installer kun findes én gang;
- kontrollér, at ingen gammel blokeret installer fortsat publiceres;
- kontrollér, at backend- og autoinstall-katalog er byte-identiske;
- kontrollér, at `expected_clientflow_version.json` matcher bridge-manifestet;
- kontrollér, at `SHA256SUMS.txt` er genereret efter sidste signering;
- kontrollér, at ændringslisten og sletningslisten er korrekte.

En release er ikke klar, hvis bare én af disse kontroller fejler.

---

# DEL D – Upload til GitHub via web

## 18. Opret branch

Opret en ny branch fra den aktuelle `main`:

```text
clientflow-release-v1-1-11
```

Ved en hotfix kan navnet eksempelvis være:

```text
clientflow-hotfix-v1-1-11
```

Brug aldrig en branch, der er baseret på en ældre ikke-deployeret commit.

---

## 19. Upload ændrede og nye filer

1. Download den leverede release-/patch-ZIP.
2. Pak den ud lokalt.
3. Åbn den nye branch i GitHub.
4. Vælg **Add file → Upload files**.
5. Træk hele ZIP-indholdet ind, så mapperne bevares.
6. Kontrollér, at filerne lander fra repoets rod og ikke i en ekstra ZIP-mappe.
7. Commit uploaden til den nye branch.

Typiske releasefiler er:

```text
clientflow-autoinstall-site/clientflow_clean_ubuntu_installer_vX_Y_Z.zip
clientflow-autoinstall-site/clientflow_release_catalog_signed.json
backend/service1/clientflow_release_catalog_signed.json
clientflow-autoinstall-site/clientflow_version_signed.json
clientflow-autoinstall-site/expected_clientflow_version.json
clientflow-autoinstall-site/SHA256SUMS.txt
FINAL_RELEASE_BASELINE.md
```

Der kan være flere filer, hvis releasen ændrer backend, frontend, installation eller protokol.

### Filer der skal slettes

Slet kun de filer, der står i den separate sletningsliste.

En gammel installer slettes normalt kun, når kataloget gør versionen `deprecated` eller `blocked`, eller retentionpolitikken kræver det.

Metadata for blokerede releases bevares i det signerede katalog.

---

## 20. Kontrollér GitHub “Files changed”

Inden pull request:

- ingen private nøgle- eller passphrasefiler;
- ingen `.env`;
- ingen `node_modules`, `dist`, `__pycache__` eller `*.pyc`;
- ingen utilsigtede database- eller environmentændringer;
- korrekt nyt versionsfilnavn;
- ingen overskrivning af tidligere installerartefakter;
- katalogkopierne ser identiske ud;
- kun de forventede filer er ændret.

Opret derefter pull request.

---

## 21. Kræv grøn CI

Pull requesten må ikke merges, før både backend- og frontendjob er grønne.

CI kontrollerer blandt andet:

- dependency-lock og audits;
- repositorykontrakt;
- ClientFlow-kontrakt;
- signeret katalog og installerhashes;
- fravær af usigneret legacykanal;
- backendtests;
- Alembic-head og offline migration-SQL;
- Ruff og Python compile;
- frontend lint, tests og build;
- versionskatalog og rollback-UI.

Ved fejl rettes releasen på samme branch. Omgå aldrig en rød sikkerheds- eller releasekontrakt.

---

# DEL E – Merge og deployment

## 22. Merge pull requesten

Når CI er grøn:

1. Merge pull requesten til `main`.
2. Notér den fulde 40-tegns Git commit-SHA.
3. Kontrollér, at Render starter deployment af både backend og frontend fra samme commit.
4. Ved databaseændringer skal Render Pre-Deploy Command fortsat være:

```text
python scripts/run_migrations.py
```

ClientFlow-releaseændringer kræver normalt ikke en migration, medmindre backendens versions- eller deploymentmodel ændres.

---

## 23. Deploy autoinstall-sitet

Deploy eller upload hele den opdaterede mappe gennem den eksisterende deploymentmekanisme for `clientflow-autoinstall-site`.

Disse filer skal være live fra samme releasegrundlag:

```text
index.html
CLIENTFLOW_START_HER.sh
clientflow_release_catalog_signed.json
clientflow_update_pubkey.pem
clientflow_clean_ubuntu_installer_vX_Y_Z.zip
alle øvrige stable/supported installerfiler
clientflow_version_signed.json
expected_clientflow_version.json
SHA256SUMS.txt
```

Kontrollér på det live site:

- kataloget kan hentes med HTTPS;
- den nye installer kan hentes;
- blokerede installerfiler giver 404 eller er på anden måde utilgængelige;
- katalogets live bytes svarer til repoets fil;
- installerens live SHA256 og størrelse svarer til kataloget;
- caching viser ikke en gammel katalogversion.

Katalog, backendkopi og installerfiler skal være deployet som én sammenhængende release. Promovér ikke versionen i Control Room, før de live filer er verificeret.

---

## 24. Kontrollér commit-provenance og health

Efter Render-deploy:

- `/health` skal returnere 200;
- `/health/db` skal returnere 200;
- backend `/version` skal vise den forventede commit;
- frontend `/release.json` skal vise samme commit;
- Production smoke test i GitHub Actions skal være grøn.

Lokal read-only kontrol:

```bash
python scripts/check_production_readiness.py \
  --base-url https://display.planiq.dk \
  --expected-product "PlanIQ Display" \
  --expected-commit FULL_40_CHARACTER_GIT_SHA
```

---

# DEL F – Canary, rollout og rollback

## 25. Test én ny factory-installation

På en testmaskine:

1. Kopiér hele `clientflow-autoinstall-site`-mappen samlet.
2. Kør:

```bash
bash CLIENTFLOW_START_HER.sh
```

3. Kontrollér at seneste stabile version er standard.
4. Kontrollér at kun `stable` og `supported` kan vælges.
5. Kontrollér at forkert eller blokeret version afvises.
6. Kontrollér Ubuntu-kompatibilitet.
7. Gennemfør factory-installationen.
8. Aktivér klienten med en gyldig installationskode.

Smoke-test:

- heartbeat og online-status;
- kalender og sleep/wake;
- livestream;
- Remote Desktop;
- userterminal;
- adminterminal;
- ClientFlow-update-status;
- Ubuntu-update-status;
- reboot og reconnect;
- serviceejerskab og root-runtime-boundary.

---

## 26. Test update fra tidligere understøttet version

Hvis en tidligere version fortsat er `supported`:

1. Installér eller brug en testklient på den tidligere version.
2. Vælg den nye stabile version i Control Room.
3. Bestil ClientFlow-update.
4. Kontrollér deployment sequence, status og audit-log.
5. Kontrollér at klienten henter og verificerer det signerede katalog.
6. Kontrollér at version, release sequence og revision opdateres korrekt.
7. Gentag den funktionelle smoke test.

---

## 27. Test kontrolleret manuel downgrade

På testklienten:

1. Vælg en understøttet tidligere version i Control Room.
2. Kontrollér at UI viser tydelig downgrade-advarsel.
3. Angiv en konkret begrundelse.
4. Bekræft som superadministrator.
5. Kontrollér at backend opretter en højere deployment sequence.
6. Kontrollér kritisk audit-log.
7. Kontrollér at klienten accepterer den signerede ordre og installerer den valgte version.
8. Smoke-test alle kritiske funktioner.

Opdatér derefter testklienten tilbage til seneste stabile version.

---

## 28. Gradvis udrulning

Efter grøn canary:

1. Udrul til en lille gruppe klienter.
2. Overvåg update-status, reconnect, logs og audit.
3. Vent med bred udrulning, indtil gruppen er stabil.
4. Udrul derefter til resten i kontrollerede batches.

En ny katalogdeployment må ikke automatisk tvangsopdatere alle klienter. Eksisterende klienter opdateres først, når en updateordre bestilles, medmindre en særskilt fremtidig rolloutfunktion er implementeret og godkendt.

---

# DEL G – Hændelser og rollback

## 29. Automatisk teknisk rollback

Hvis installationen fejler under selve updateprocessen, skal ClientFlow lokalt forsøge at gendanne:

- tidligere programkode;
- tidligere Python-runtime;
- tidligere konfiguration;
- tidligere fungerende services.

Dette er automatisk recovery og er ikke det samme som en administratorbestilt downgrade.

Kontrollér efter en fejl:

- `client_update_status`;
- fejlet trin og fejlbesked;
- service-status;
- hvilken version klienten reelt kører;
- om rollbacken gennemførte fuldt.

---

## 30. Manuel rollback af en funktionelt fejlbehæftet release

Hvis den nye version installerer korrekt, men har en produktfejl:

1. Stop bred udrulning.
2. Vælg den seneste kendt gode `supported` version i Control Room.
3. Gennemfør auditeret downgrade på berørte klienter.
4. Opdatér katalogpolitikken, hvis den nye version ikke længere må vælges.
5. Øg `catalog_sequence`.
6. Signér kataloget på ny.
7. Deploy katalog og backendkopi.

Den tidligere installer må ikke ændres; den eksisterende understøttede artefakt anvendes.

---

## 31. Akut blokering af en release

Hvis en version har en sikkerhedsfejl eller alvorlig inkompatibilitet:

1. Sæt katalogposten til:

```json
{
  "status": "blocked",
  "installable": false,
  "update_allowed": false,
  "rollback_allowed": false,
  "block_reason": "Konkret årsag"
}
```

2. Fjern installerfilen fra autoinstall-sitet og repoet.
3. Bevar releasepostens historiske metadata.
4. Vælg en kendt god version som `latest_stable` og `default_install_version`.
5. Øg `catalog_sequence`.
6. Signér kataloget igen.
7. Kopiér det byte-identisk til backend.
8. Regenerér `SHA256SUMS.txt`.
9. Kør alle kontroller.
10. Deploy straks gennem normal pull request og grøn CI.
11. Bestil kontrolleret downgrade eller forward-fix for berørte klienter.

Genbrug aldrig det blokerede versionsnummer til et nyt artefakt.

---

# DEL H – Afslut releasen

## 32. Opdatér produktionsbaseline

Når release og smoke test er grønne, registrér mindst:

- ClientFlow-version;
- release sequence;
- catalog sequence;
- revision og patch;
- installerfil;
- installer-SHA256 og størrelse;
- payload-SHA256;
- signerings-key ID;
- latest stable;
- supported/deprecated/blocked versioner;
- Alembic-head;
- deploymentcommit;
- dato for fysisk smoke test.

Opdatér:

```text
FINAL_RELEASE_BASELINE.md
```

---

## 33. Opbevar releasebeviserne

Bevar:

- mergecommit;
- grøn CI;
- testrapport;
- deploymentvejledning;
- ændringsliste;
- sletningsliste;
- installerens SHA256;
- katalogets SHA256;
- fysisk smoke-testresultat;
- audit-log for testupdate og testdowngrade.

Den private nøgle og passphrase opbevares fortsat i mindst to kontrollerede offlinekopier og hver for sig.

---

# Hurtig afkrydsningsliste

## Releaseforberedelse

- [ ] Frisk repo fra aktuel produktion.
- [ ] Ny semantisk version valgt.
- [ ] Ny, ubrugt `release_sequence` valgt.
- [ ] Højere `catalog_sequence` valgt.
- [ ] Kompatibilitet og Ubuntu-versioner defineret.
- [ ] Ny versionsbestemt installer bygget.
- [ ] Factory-state er neutral.
- [ ] Ingen credentials eller private keys i pakken.
- [ ] Root-runtime-boundary er bevaret.
- [ ] Installer-SHA256, størrelse og payload-SHA256 beregnet.

## Katalog og signering

- [ ] Ny releasepost tilføjet.
- [ ] Tidligere versioners status er vurderet.
- [ ] `latest_stable` og `default_install_version` er korrekte.
- [ ] Kataloget er signeret offline.
- [ ] Backendkopien matcher byte-for-byte.
- [ ] 1.1.9-bridge er opdateret og signeret, hvis 1.1.9 fortsat understøttes.
- [ ] `expected_clientflow_version.json` matcher bridgefilen.
- [ ] `SHA256SUMS.txt` er genereret efter sidste ændring.

## Tests

- [ ] Repository-validator grøn.
- [ ] ClientFlow-kontrakt grøn.
- [ ] Dependency-kontrakt og audits grønne.
- [ ] Backendtests grønne.
- [ ] Alembic-head og offline SQL grønne.
- [ ] Ruff og Python compile grønne.
- [ ] Frontend lint 0/0.
- [ ] Frontendtests og build grønne.
- [ ] Ingen secrets eller genererede filer i leverancen.

## GitHub og deploy

- [ ] Ny branch fra aktuel `main`.
- [ ] Kun ændrede/nye filer uploadet.
- [ ] Kun filer fra sletningslisten slettet.
- [ ] “Files changed” manuelt gennemgået.
- [ ] Pull request CI grøn.
- [ ] Mergecommit noteret.
- [ ] Backend og frontend deployet på samme commit.
- [ ] Autoinstall-sitet har samme katalog og installerbytes.
- [ ] `/health`, `/health/db`, `/version` og `/release.json` verificeret.
- [ ] Production smoke test grøn.

## Fysisk ClientFlow-test

- [ ] Factory-installation af seneste stabile version grøn.
- [ ] Update fra tidligere understøttet version grøn.
- [ ] Auditeret downgrade grøn.
- [ ] Forward update tilbage til seneste stabile grøn.
- [ ] Livestream grøn.
- [ ] Remote Desktop grøn.
- [ ] User- og adminterminal grøn.
- [ ] Kalender og sleep/wake grøn.
- [ ] Ubuntu-update-status grøn.
- [ ] Reboot og reconnect grøn.
- [ ] Releasebaseline opdateret.

---

## 34. Definition of done

En ClientFlow-release er først færdig, når:

1. releaseartefaktet er uforanderligt og verificeret;
2. det signerede katalog er korrekt og live;
3. backend og autoinstall-site bruger samme katalogbytes;
4. CI og dependency-audits er grønne;
5. Render og autoinstall-site er deployet korrekt;
6. én fysisk klient har bestået de relevante factory-, update- og tilladte rollbackforløb;
7. alle kritiske funktioner har bestået smoke test;
8. produktionsbaselinen er opdateret;
9. ingen blokeret eller usigneret version kan installeres.

## Ubuntu-generationsskift

Ubuntu Desktop LTS fra og med 26.04 på `amd64` med GNOME Wayland er den aktuelle platformbaseline. Ubuntu 26.04 er certificeret til ClientFlow 1.1.19. En nyere LTS må kun fortsætte, hvis den signerede minimumspolitik matcher og den obligatoriske pakke-, GDM-, GNOME- og Wayland-preflight består før systemændringer. Historiske releases bruger fortsat eksakte `ubuntu_versions`, og rollback til en inkompatibel Ubuntu-generation afvises.


## Permanent update-pipeline-kontrakt fra ClientFlow 1.1.16

- Arkivstier normaliseres segmentvist; `lstrip("./")` er forbudt i sikkerhedsvalidering.
- En ren TAR-root directory (`.` eller `./`) må accepteres, men payload-buildet bør udelade den for maksimal forward-kompatibilitet.
- Absolutte stier, traversal, Windows-drevstier, dubletmedlemmer, links og specialfiler afvises før extraction.
- Backendens `client_update_deployment_sequence` er primær ordreidentitet; `client_update_requested_at` er backend-ejet metadata og skal merges ned på klienten.
- En stale lokal status-/fejltekst må aldrig alene definere, om en ny updateordre er en dublet.

## Permanent self-update permissions- og versionskontrakt fra ClientFlow 1.1.19

- En root-updater med `UMask=0077` må ikke efterlade `/opt/clientflow/venv` utilgængelig for den begrænsede `clientflow`-servicebruger. Venv skal slutte som `root:root` med `a+rX,go-w`.
- `/opt/clientflow/api` og runtime-JSON skal efter installation og efter updaterens sidste status-write være `clientflow:clientflow` og kunne atomisk erstattes af servicebrugeren.
- Installerens version, patch, revision og release sequence er hardkodet i det immutable artefakt. Caller-felter må ikke kunne omskrive identiteten.
- `/etc/clientflow/clientflow.env` er eneste systemd-kilde til `CLIENTFLOW_VERSION` og `CLIENTFLOW_VERSION_PATCH`; `05-clientflow-version.conf` er forbudt.
- Legacy updater-processens sidste root-skrivninger håndteres af en særskilt post-update integrity-service, som kører efter `clientflow_self_update.service`.
- Forrige venv og env-backup må først slettes, når den nye version har bestået servicebruger-, identity- og servicestatuskontrol.
- En release må ikke godkendes alene på repository-tests. Den skal pilottestes som reel frontend-initieret update og som ren factory-installation.

### 1.1.18 pilot gate

Bred udrulning kræver grøn fysisk update fra repareret 1.1.16, reel rollback-test, samtidig Remote Desktop/livestream, sessionskift og mindst 60 minutters stabil livestream.
