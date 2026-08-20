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
- Den godkendte bundle skal via manifestets `fresh_installer` binde det eksakte installer-filnavn, størrelse og SHA-256; installer-PYZ må først eksekveres efter ekstern hashverifikation mod den allerede verificerede bundle.
- Gyldig one-time enrollmentkode og HTTPS-forbindelse til backend.
- Eventuel privat CA leveres som PEM og kopieres til `/etc/clientflow/tls/ca.pem`.

## Fresh-install flow

1. Verificér først den godkendte bundle mod den eksternt kendte approved bundle-SHA-256 med hostens `sha256sum`. Udpak derefter kun `manifest.json` fra de verificerede bundle-bytes og verificér installer-PYZ'ens filnavn, størrelse og SHA-256 mod manifestets `fresh_installer`. Ingen installer-kode må være kørt endnu. Se `CLIENTFLOW_RELEASE_PROCEDURE.md` for den canonical kommando-blok.

2. Kør derefter den eksternt verificerede installer-PYZ i Python isolated mode og verificér bundlen igen gennem installerens egen release-parser:

   ```bash
   /usr/bin/python3 -I ./clientflow-installer-1.3.0.pyz verify \
     --bundle ./clientflow-1.3.0-seq-1201-approved.tar \
     --expected-bundle-sha256 <APPROVED_BUNDLE_SHA256>
   ```

3. Kør `install` som root med **samme** verificerede installer, bundle-SHA-256, backend-origin, enrollmentkode og kioskbruger:

   ```bash
   sudo /usr/bin/python3 -I ./clientflow-installer-1.3.0.pyz install \
     --bundle ./clientflow-1.3.0-seq-1201-approved.tar \
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
sudo /usr/bin/python3 -I "$INSTALLER" activate \
  --release-id clientflow-1.3.0-seq-1201 \
  --approval-reference CHANGE-REFERENCE
```

Aktivering opdaterer systemd-definitioner, skifter det atomiske `active`-symlink, starter `clientflow.target` og gennemfører health checks. Fejl udløser automatisk rollback.

## Eksplicit wipe

Wipe er ikke en skjult installerfunktion. Den kræver både en konkret begrundelse og den eksakte streng `DESTROY-CLIENTFLOW-STATE`. Proceduren må kun anvendes efter særskilt godkendelse og sletter ClientFlow-state, users, groups, units og releases.
