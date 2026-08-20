# ClientFlow 1.3.0 — keyless release, godkendelse og rollback

## Én versionskilde

`VERSION` indeholder `1.3.0` og er den eneste manuelt vedligeholdte produktversion. Filnavne, payload-root, release-ID og manifestværdier genereres. Release sequence vedligeholdes separat i `release/release-input.json`, fordi den er en monoton anti-rollback-værdi og ikke en alternativ versionskilde.

Runtime-wheelets PEP 621-version er også dynamisk bundet til denne authority via `clientflow_runtime.version.VERSION`; `client/runtime/pyproject.toml` indeholder derfor ingen separat statisk produktversion. I source/build-kontekst læser modulet `client/VERSION`; i installeret runtime rapporterer det versionen fra wheelets egen distributionsmetadata. Dermed kan en staged runtime ikke arve versionsnummeret fra et ældre `/opt/clientflow/active`-target.

## Sikkerhedsmodel uden release-signeringsnøgler

ClientFlow 1.3.0 bruger **ingen privat eller offentlig release-signeringsnøgle**. Der oprettes, gemmes eller anvendes ingen release-signatur. SHA-256 bruges til integritetsbinding, mens releasegodkendelse er en eksplicit procesgate bundet til den eksakte kandidat-SHA-256 og det eksakte source commit.

Denne model giver fail-closed integritetskontrol og sporbarhed, men den påstår ikke kryptografisk signer-identitet. Tillidsgrænsen er derfor den kontrollerede GitHub-proces, branch/review-beskyttelse, adgang til build-artifacts, HTTPS-transport og den eksplicitte manuelle releasegodkendelse.

Andre ClientFlow-nøgler, eksempelvis enrollment/systemkryptering og kortlivede root-terminal-grants, er separate runtime-sikkerhedsmekanismer og berøres ikke af den keyless release-model.

## Reproducerbar keyless release candidate

Canonical release candidates bygges i `.github/workflows/release-build.yml`. Workflowet er manuelt, men accepterer kun en eksakt source SHA, som er workflowets egen dispatch-SHA og allerede har en successful canonical CI push-run. Buildet bruger repoets hash-låste platform-inputs og den eksplicit pinnede Python/pip/setuptools-toolchain.

To uafhængige GitHub runners bygger samme commit med commit-timestamp som `SOURCE_DATE_EPOCH`. En separat reproducibility-job kræver byte-identiske candidate-, installer-, payload-, manifest- og checksum-bytes, skriver `REPRODUCIBILITY.json` og uploader først derefter én unapproved handoff. Approval og publication er fortsat separate gates og findes ikke i release-build workflowet.

Et almindeligt candidate-manifest har altid:

```yaml
artifact_type: runtime_release
install_modes:
  - fresh_install
  - in_place_update
deployable: false
integrity_algorithm: sha256
release_approval:
  reference: null
  candidate_sha256: null
activation:
  automatic: false
  automatic_reboot: false
```

Builderen kræver et rent Git-worktree og den eksakte toolchain fra `client/release/release-build-toolchain.json`. TAR- og ZIP-metadata normaliseres til fast epoch, root-ejerskab, deterministisk rækkefølge og kontrollerede modes. Installerpayloaden indeholder kun de nødvendige runtime-definitioner, helpers, konfiguration, releasekode og driftsdokumentation; backend-, frontend-, runtime-source- og testtræer installeres ikke på klienten.

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
  ./clientflow-1.3.0-seq-1201-candidate.tar \
  --output ./clientflow-1.3.0-seq-1201-approved.tar \
  --expected-candidate-sha256 <EXACT_CANDIDATE_SHA256> \
  --expected-installer-sha256 <EXACT_INSTALLER_SHA256> \
  --expected-source-commit <FULL_40_CHARACTER_GIT_SHA> \
  --approval-reference <CHANGE_OR_RELEASE_REFERENCE> \
  --approve-release
```

Godkendelsesgaten afviser kandidaten, hvis SHA-256 eller source commit afviger, source er dirty, offline runtime ikke er komplet, eller runtime-preflight fejler. Kandidaten åbnes én gang med no-follow semantics; dens hash, manifest, payload og runtime-preflight er derfor bundet til samme åbne filidentitet, også hvis pathname udskiftes under approval. Først derefter sættes:

```yaml
deployable: true
release_approval:
  reference: <approval-reference>
  candidate_sha256: <exact candidate SHA-256>
```

Outputbundlens egen SHA-256 skal derefter registreres og bruges som den eksakte transport-/installationsbinding. Kandidat- og approved-manifestet binder samtidig fresh-installerens eksakte filnavn, størrelse og SHA-256; schema 8 læser installer-bytes fra den samme pinned bundle, og approval-gaten kræver den eksplicit forventede installer-hash.

## Publicering og verificeret releasekatalog

Backendvariablen `CLIENTFLOW_RELEASE_ARTIFACT_DIR` skal pege på et eksisterende katalog, ejet af root eller backend-processens UID, med **godkendte keyless `.tar`-bundles**. Kataloget må ikke være et symlink eller være gruppe-/verdensskrivbart. Releasekatalogets metadata kan fortsat læses uden artifact-store, men en deployment kan ikke autoriseres, og artifact-endpointet returnerer fail-closed, før den eksakte approved bundle er publiceret.

Der findes ingen `CLIENTFLOW_RELEASE_PUBLIC_KEY_PATH` og ingen release trust key. Frontend modtager aldrig en release, før backend har verificeret:

- eksakt archive-layout og sikre metadata;
- produkt, `clientflow-runtime-release`-kanal, `runtime_release` artifact-type, eksplicit `in_place_update` install-mode og release-ID;
- `deployable: true`;
- `integrity_algorithm: sha256`;
- gyldig `release_approval.reference` og kandidat-SHA-256;
- payloadstørrelse og payload-SHA-256;
- komplet offline wheelhouse og ren source-commit;
- manuel aktivering og ingen automatisk reboot.

Backend beregner desuden SHA-256 for hele den publicerede bundle og kopierer release-ID, størrelse, bundle-SHA-256, approval-reference, candidate-SHA og source commit ind i den immutable deployment-authorization. Artifactet publiceres eksplicit med en separat gate; backend/frontend bygger eller godkender ikke selv releasen:

```bash
python scripts/publish_clientflow_release.py \
  ./clientflow-1.3.0-seq-1201-approved.tar \
  --artifact-dir /srv/clientflow-release-artifacts \
  --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256> \
  --expected-approval-reference <CHANGE_OR_RELEASE_REFERENCE> \
  --expected-source-commit <FULL_40_CHARACTER_GIT_SHA> \
  --publish-release
```

Publicering holder både den verificerede approved bundle og artifact-store-kataloget åbent som pinned file descriptors gennem hele operationen. Copy sker fra den samme source-handle, som leverede manifest, payload og whole-bundle SHA-256; source og staged copy hashes igen før atomic no-replace link. Publicering er kun idempotent for identiske allerede-publicerede bytes, når den eksisterende fil samtidig er en sikker regular file med korrekt ownership/mode. Samme release-ID med andre bytes eller usikre metadata afvises.

## Download, stage og anti-rollback

Den stabile updater skal først hente en kortlivet deployment-bound artifact-authorization og downloader derefter kun den eksakte same-origin-sti `/api/clientflow/release-artifacts/<release-id>` med DPoP-bound artifact-token. Legacy System-domain Bearer-token accepteres ikke af endpointet. Den senere root-controller skal derefter binde de samme release-ID/size/SHA-værdier til secure ingest før ekstraktion.

En verificeret bundle stages i et immutable katalog:

```text
/opt/clientflow/releases/clientflow-1.3.0-seq-<sequence>/
```

En release sequence, der ikke er større end den højeste tidligere accepterede sequence, afvises. Stage ændrer ikke `active` og starter ingen services.

Hvis processen afbrydes efter den immutable release er flyttet på plads, men før transaktionsstate er gemt, kan kataloget kun adopteres ved næste kørsel, når manifestet og source-tree-digest matcher den verificerede bundle nøjagtigt. Et ændret eller ukendt orphan-katalog afvises.

## Fresh installer

Manifest schema 8 gør fresh installer-PYZ'en til et fysisk medlem af selve approved bundlen. Den eksterne whole-bundle SHA-256 er derfor eneste bootstrap trust-anchor. Den canonical host-handoff holder bundle-identiteten pinned gennem hash, manifestlæsning og installer-extraction og materialiserer derefter root-owned private bundle/installer-copies under `/run` før første installer-execution. Den konkrete procedure står i `CLIENTFLOW_RELEASE_PROCEDURE.md`.

Først derefter må den verificerede installer køre i isolated mode:

```bash
sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" verify \
  --bundle ./clientflow-1.3.0-seq-1201-approved.tar \
  --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256>
```

`install` kræver samme `--expected-bundle-sha256`; værdien gemmes i resumérbar install-state, så resume ikke kan skifte til en anden bundle.

## Aktivering

`/opt/clientflow/active` er et atomisk active-symlink til den valgte immutable release. Staging bruger én pinned bundle-identitet og persisterer whole-bundle SHA-256/size, candidate SHA-256, source commit og immutable release-approval reference i release-state. Aktivering kræver `--expected-release-approval-reference`, som skal matche artifactets allerede bundne approval-reference; operatøren kan ikke omskrive provenance ved activation. Derefter opdateres managed systemd/sysusers/tmpfiles-definitioner, target startes og health checks køres.

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

Manuel rollback kræver både målreleaseens eksakte `--expected-release-approval-reference` og en begrundelse. Referencen skal matche den immutable approval, som allerede er gemt for rollbackmålet; den er ikke en ny fri rollback-reference. Rollback kan kun gå til en allerede installeret, verificeret release. Anti-rollback forhindrer genindlæsning af gamle bundles, men forhindrer ikke kontrolleret rollback til en allerede installeret immutable release.

## Offline runtime input

Python-runtime og tredjeparts-wheels er release-inputs, ikke source. De leveres til `scripts/build_clientflow_release.py --runtime-inputs ...`. Builderen genbygger altid ClientFlow-wheelet fra `client/runtime/`, så et ældre prebuilt ClientFlow-wheel ikke kan overskrive den canonical source.
