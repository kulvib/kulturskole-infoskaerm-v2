# ClientFlow 1.3.0 — fresh installation from a canonical runtime release

## Sikkerhedsstatus

ClientFlow 1.3.0 bruger en **keyless release-model**. Der oprettes, gemmes eller anvendes ingen privat eller offentlig release-signeringsnøgle. En normal build er en reproducerbar, verificeret release candidate med `deployable: false`. Kun en separat manuel godkendelsesgate kan producere en `deployable: true`-bundle.

Ingen fysisk installation må ske, før en konkret pilotklient er udpeget og installationen er særskilt godkendt.

ClientFlow 1.3.0 er den canonical bootstrap-baseline for den nye updater-plane. Backendens releasekatalog afviser derfor in-place deployment af 1.3.0 til pre-1.3 installationer; disse skal installeres fresh. Senere canonical releases kan eksplicit åbne update-kompatibilitet fra 1.3.0.

## Forudsætninger for en senere godkendt installation

- Ny Ubuntu Desktop LTS 26.04 `amd64`-installation.
- Eksisterende interaktiv, uprivilegeret kioskbruger.
- Ingen eksisterende ClientFlow-filer, systemd-units, Linux-brugere eller state.
- Godkendt keyless bundle med `deployable: true`, gyldig `release_approval`, SHA-256-integritetsmetadata og monoton release sequence.
- Den eksakte SHA-256 for **hele** den godkendte bundle skal være kendt via den godkendte releaseproces, før nogen installer-kode køres.
- Manifest schema 8 kræver, at den godkendte bundle fysisk indeholder fresh-installerens eksakte bytes og binder dem via `fresh_installer` filnavn/størrelse/SHA-256. Der findes ingen separat installer-path authority.
- Gyldig one-time enrollmentkode og HTTPS-forbindelse til backend.
- Eventuel privat CA leveres som PEM og kopieres til `/etc/clientflow/tls/ca.pem`.

## Fresh-install flow

1. Åbn approved bundle-pathen én gang i den canonical host-bootstrap, verificér den åbne filidentitet mod den eksternt kendte whole-bundle SHA-256, og udtræk installer-memberen fra **samme åbne bundle**. Materialisér både bundle og installer som root-owned private copies under `/run`. Se `CLIENTFLOW_RELEASE_PROCEDURE.md` for den canonical blok.

2. Kør derefter kun den private root-owned installer-copy i Python isolated mode og verificér den private bundle-copy gennem installerens egen release-parser:

   ```bash
   sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" verify \
     --bundle "$BOOTSTRAP_BUNDLE" \
     --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256>
   ```

3. Kør `install` som root med **samme private bootstrap-filer**, bundle-SHA-256, backend-origin, enrollmentkode og kioskbruger:

   ```bash
   sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" install \
     --bundle "$BOOTSTRAP_BUNDLE" \
     --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256> \
     --backend-url https://<backend-origin> \
     --enrollment-code <one-time-code> \
     --kiosk-user <kiosk-user>
   ```

4. Installeren afviser alle eksisterende ClientFlow-spor. En geninstallation kræver den separate wipe-procedure med eksakt destruktiv bekræftelse.
5. Hele bundlens SHA-256 verificeres før bundlefortolkning. Derefter verificeres manifest-schema, produkt, `runtime_release`, `fresh_install` install-mode, deployable-gate, keyless release approval, payloadstørrelse/-SHA-256, arkivstier, dubletter, links, specialfiler og komplet offline runtime.
6. Releasen stages i `/opt/clientflow/releases/<release-id>` og gøres immutable.
7. Separate sysusers, kataloger og systemd-definitioner materialiseres, men `clientflow.target` forbliver disabled og inaktiv.
8. Installeren genererer en lokal RSA 3072-**systemkrypteringsnøgle** til enrollment. Det er ikke en release-signeringsnøgle.
9. Seks domænecredentials skrives separat for status, display, livestream, Remote Desktop, terminal og system.
10. En eventuel privat CA kopieres til den root-ejede ClientFlow-konfiguration og genbruges ved resume; installationen er ikke afhængig af den oprindelige inputfil efter første sikre kopi.
11. Standardkonfiguration, root-grant-verifikation og credentials valideres med sikre filrettigheder.
12. Installationen stopper ved status `pending_manual_activation`.

Der er **ingen automatisk reboot**, ingen automatisk aktivering, ingen åbning af Terminal eller Remote Desktop og ingen start af en livestream.

## Manuel aktivering

Aktivering er et separat trin og kræver en konkret approval-reference:

```bash
sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" activate \
  --release-id clientflow-1.3.0-seq-1201 \
  --approval-reference CHANGE-REFERENCE
```

Aktivering opdaterer systemd-definitioner, skifter det atomiske `active`-symlink, starter `clientflow.target` og gennemfører health checks. Fejl udløser automatisk rollback.

## Eksplicit wipe

Wipe er ikke en skjult installerfunktion. Den kræver både en konkret begrundelse og den eksakte streng `DESTROY-CLIENTFLOW-STATE`. Proceduren må kun anvendes efter særskilt godkendelse og sletter ClientFlow-state, users, groups, units og releases.
