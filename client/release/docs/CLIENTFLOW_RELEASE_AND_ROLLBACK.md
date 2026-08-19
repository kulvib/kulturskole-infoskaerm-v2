# ClientFlow 1.2.0 — keyless release, godkendelse og rollback

## Én versionskilde

`VERSION` indeholder `1.2.0` og er den eneste manuelt vedligeholdte produktversion. Filnavne, payload-root, release-ID og manifestværdier genereres. Release sequence vedligeholdes separat i `release/release-input.json`, fordi den er en monoton anti-rollback-værdi og ikke en alternativ versionskilde.

## Sikkerhedsmodel uden release-signeringsnøgler

ClientFlow 1.2.0 bruger **ingen privat eller offentlig release-signeringsnøgle**. Der oprettes, gemmes eller anvendes ingen release-signatur. SHA-256 bruges til integritetsbinding, mens releasegodkendelse er en eksplicit procesgate bundet til den eksakte kandidat-SHA-256 og det eksakte source commit.

Denne model giver fail-closed integritetskontrol og sporbarhed, men den påstår ikke kryptografisk signer-identitet. Tillidsgrænsen er derfor den kontrollerede GitHub-proces, branch/review-beskyttelse, adgang til build-artifacts, HTTPS-transport og den eksplicitte manuelle releasegodkendelse.

Andre ClientFlow-nøgler, eksempelvis enrollment/systemkryptering og kortlivede root-terminal-grants, er separate runtime-sikkerhedsmekanismer og berøres ikke af den keyless release-model.

## Reproducerbar keyless release candidate

```bash
SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" \
python scripts/build_clientflow_release.py \
  --repo . \
  --output-dir ./build/clientflow-1.2.0
```

Et almindeligt build har altid:

```yaml
deployable: false
integrity_algorithm: sha256
release_approval:
  reference: null
  candidate_sha256: null
activation:
  automatic: false
  automatic_reboot: false
```

Builderen kræver normalt et rent Git-worktree. TAR- og ZIP-metadata normaliseres til fast epoch, root-ejerskab, deterministisk rækkefølge og kontrollerede modes. Installerpayloaden indeholder kun de nødvendige runtime-definitioner, helpers, konfiguration, releasekode og driftsdokumentation; backend-, frontend-, runtime-source- og testtræer installeres ikke på klienten.

## Offline runtime

En godkendelig kandidat kræver:

- en `amd64` Python-runtime, der reelt rapporterer `3.13.14`;
- hashdeklarerede wheels for ClientFlow-runtime og samtlige låste runtimeafhængigheder;
- installation med `--no-index` fra det medfølgende wheelhouse;
- succesfuld import af den installerede ClientFlow-runtime;
- Ubuntu 26.04-preflight;
- byte-identisk reproducerbarhed mellem to builds.

Manglende eller ubrugelig runtime betyder, at kandidaten forbliver ikke deploybar.

## Manuel keyless releasegodkendelse

Godkendelse er et separat trin og bruger ingen secret eller signing key. Godkendelsen skal være bundet til den eksakte kandidatfil og det eksakte source commit:

```bash
python scripts/approve_clientflow_release.py \
  ./clientflow-1.2.0-seq-1200-candidate.tar \
  --output ./clientflow-1.2.0-seq-1200-approved.tar \
  --expected-candidate-sha256 <EXACT_CANDIDATE_SHA256> \
  --expected-source-commit <FULL_40_CHARACTER_GIT_SHA> \
  --approval-reference <CHANGE_OR_RELEASE_REFERENCE> \
  --approve-release
```

Godkendelsesgaten afviser kandidaten, hvis SHA-256 eller source commit afviger, source er dirty, offline runtime ikke er komplet, eller runtime-preflight fejler. Først derefter sættes:

```yaml
deployable: true
release_approval:
  reference: <approval-reference>
  candidate_sha256: <exact candidate SHA-256>
```

Outputbundlens egen SHA-256 skal derefter registreres og bruges som den eksakte transport-/installationsbinding.

## Publicering og verificeret releasekatalog

Backendvariablen `CLIENTFLOW_RELEASE_ARTIFACT_DIR` skal pege på et eksisterende, root-ejet katalog med **godkendte keyless `.tar`-bundles**. Kataloget må ikke være et symlink eller være gruppe-/verdensskrivbart. Uden denne konfiguration returnerer katalogendpointet HTTP 503, og Control Room kan ikke stage en release.

Der findes ingen `CLIENTFLOW_RELEASE_PUBLIC_KEY_PATH` og ingen release trust key. Frontend modtager aldrig en release, før backend har verificeret:

- eksakt archive-layout og sikre metadata;
- produkt, `fresh-only-release`-kanal og release-ID;
- `deployable: true`;
- `integrity_algorithm: sha256`;
- gyldig `release_approval.reference` og kandidat-SHA-256;
- payloadstørrelse og payload-SHA-256;
- komplet offline wheelhouse og ren source-commit;
- manuel aktivering og ingen automatisk reboot.

Backend beregner desuden SHA-256 for hele den publicerede bundle. Systemkommandoen binder release-ID, størrelse og denne bundle-SHA-256 til downloadet. Artifactet skal publiceres immutabelt af en separat godkendt proces; backend/frontend bygger eller godkender ikke selv releasen.

## Download, stage og anti-rollback

Systemagenten downloader kun den eksakte same-origin-sti `/api/clientflow/release-artifacts/<release-id>` og verificerer den forventede størrelse og bundle-SHA-256. Root-transaktionen kræver den samme SHA-256 igen via `--expected-bundle-sha256` **før ekstraktion**.

En verificeret bundle stages i et immutable katalog:

```text
/opt/clientflow/releases/clientflow-1.2.0-seq-<sequence>/
```

En release sequence, der ikke er større end den højeste tidligere accepterede sequence, afvises. Stage ændrer ikke `active` og starter ingen services.

Hvis processen afbrydes efter den immutable release er flyttet på plads, men før transaktionsstate er gemt, kan kataloget kun adopteres ved næste kørsel, når manifestet og source-tree-digest matcher den verificerede bundle nøjagtigt. Et ændret eller ukendt orphan-katalog afvises.

## Fresh installer

Installerens `verify` og `install` kræver den eksakte, på forhånd kendte SHA-256 for hele den godkendte bundle:

```bash
clientflow-installer verify \
  ./clientflow-1.2.0-seq-1200-approved.tar \
  --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256>
```

`install` kræver samme `--expected-bundle-sha256`; værdien gemmes i resumérbar install-state, så resume ikke kan skifte til en anden bundle.

## Aktivering

`/opt/clientflow/active` er et atomisk active-symlink til den valgte immutable release. Aktivering kræver approval-reference, opdaterer managed systemd/sysusers/tmpfiles-definitioner, starter target og kører health checks.

## Automatisk rollback

Hvis en ny aktivering fejler:

1. Target stoppes.
2. Tidligere definitionssæt gendannes.
3. `active`-symlink skiftes tilbage.
4. Tidligere target startes.
5. Health checks køres på den gendannede release.
6. Resultatet skrives i det root-ejede transaktionsstate.

Hvis også rollback fejler, markeres transaktionen eksplicit som fejlet; der fortsættes ikke skjult.

## Manuel rollback

Manuel rollback kræver både approval-reference og begrundelse. Rollback kan kun gå til en allerede installeret, verificeret release. Anti-rollback forhindrer genindlæsning af gamle bundles, men forhindrer ikke kontrolleret rollback til en allerede installeret immutable release.

## GitHub Actions-bygget offline runtime

Workflowet `.github/workflows/clientflow-offline-runtime.yml`:

- bruger Python `3.13.14` og den daterede officielle Ubuntu 26.04-image `ubuntu:resolute-20260707`;
- verificerer CPython-kildearkivet og pip-wheel med fastlåste SHA-256-værdier;
- bygger `python-runtime-amd64.tar` og de tilladte wheel-distributioner i en isoleret container;
- udfører to builds med samme image og afviser enhver forskel i filindhold eller mode;
- bygger en keyless release candidate med `offline_wheelhouse_complete: true`;
- kører den samme offline runtime-preflight, som godkendelsesgaten kræver, inde i Ubuntu 26.04;
- uploader kun et artifact med `deployable: false`, `integrity_algorithm: sha256`, tom `release_approval`, manuel aktivering og ingen automatisk reboot.

Workflowet har kun `contents: read`, bruger ingen release secrets og kan hverken godkende, deploye eller installere på en fysisk klient. Outputtet er et verificeret releaseinput, ikke en godkendt release.
