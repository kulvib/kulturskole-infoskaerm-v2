# ClientFlow 1.2.0 — fresh-only installation

## Sikkerhedsstatus

ClientFlow 1.2.0 bruger en **keyless release-model**. Der oprettes, gemmes eller anvendes ingen privat eller offentlig release-signeringsnøgle. En normal build er en reproducerbar, verificeret release candidate med `deployable: false`. Kun en separat manuel godkendelsesgate kan producere en `deployable: true`-bundle.

Ingen fysisk installation må ske, før en konkret pilotklient er udpeget og installationen er særskilt godkendt.

## Forudsætninger for en senere godkendt installation

- Ny Ubuntu Desktop LTS 26.04 `amd64`-installation.
- Eksisterende interaktiv, uprivilegeret kioskbruger.
- Ingen eksisterende ClientFlow-filer, systemd-units, Linux-brugere eller state.
- Godkendt keyless bundle med `deployable: true`, gyldig `release_approval`, SHA-256-integritetsmetadata og monoton release sequence.
- Den eksakte SHA-256 for **hele** den godkendte bundle skal være kendt via den godkendte releaseproces, før `verify` eller `install` køres.
- Gyldig one-time enrollmentkode og HTTPS-forbindelse til backend.
- Eventuel privat CA leveres som PEM og kopieres til `/etc/clientflow/tls/ca.pem`.

## Fresh-only flow

1. Kør installerens `verify` med den eksakte forventede bundle-SHA-256:

   ```bash
   clientflow-installer verify \
     --bundle ./clientflow-1.2.0-seq-1200-approved.tar \
     --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256>
   ```

2. Kør `install` som root med **samme** bundle-SHA-256, backend-origin, enrollmentkode og kioskbruger:

   ```bash
   sudo clientflow-installer install \
     --bundle ./clientflow-1.2.0-seq-1200-approved.tar \
     --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256> \
     --backend-url https://<backend-origin> \
     --enrollment-code <one-time-code> \
     --kiosk-user <kiosk-user>
   ```

3. Installeren afviser alle eksisterende ClientFlow-spor. En geninstallation kræver den separate wipe-procedure med eksakt destruktiv bekræftelse.
4. Hele bundlens SHA-256 verificeres før bundlefortolkning. Derefter verificeres manifest-schema, produkt, fresh-only, deployable-gate, keyless release approval, payloadstørrelse/-SHA-256, arkivstier, dubletter, links, specialfiler og komplet offline runtime.
5. Releasen stages i `/opt/clientflow/releases/<release-id>` og gøres immutable.
6. Separate sysusers, kataloger og systemd-definitioner materialiseres, men `clientflow.target` forbliver disabled og inaktiv.
7. Installeren genererer en lokal RSA 3072-**systemkrypteringsnøgle** til enrollment. Det er ikke en release-signeringsnøgle.
8. Seks domænecredentials skrives separat for status, display, livestream, Remote Desktop, terminal og system.
9. En eventuel privat CA kopieres til den root-ejede ClientFlow-konfiguration og genbruges ved resume; installationen er ikke afhængig af den oprindelige inputfil efter første sikre kopi.
10. Standardkonfiguration, root-grant-verifikation og credentials valideres med sikre filrettigheder.
11. Installationen stopper ved status `pending_manual_activation`.

Der er **ingen automatisk reboot**, ingen automatisk aktivering, ingen åbning af Terminal eller Remote Desktop og ingen start af en livestream.

## Manuel aktivering

Aktivering er et separat trin og kræver en konkret approval-reference:

```bash
clientflow-installer activate \
  --release-id clientflow-1.2.0-seq-1200 \
  --approval-reference CHANGE-REFERENCE
```

Aktivering opdaterer systemd-definitioner, skifter det atomiske `active`-symlink, starter `clientflow.target` og gennemfører health checks. Fejl udløser automatisk rollback.

## Eksplicit wipe

Wipe er ikke en skjult installerfunktion. Den kræver både en konkret begrundelse og den eksakte streng `DESTROY-CLIENTFLOW-STATE`. Proceduren må kun anvendes efter særskilt godkendelse og sletter ClientFlow-state, users, groups, units og releases.
