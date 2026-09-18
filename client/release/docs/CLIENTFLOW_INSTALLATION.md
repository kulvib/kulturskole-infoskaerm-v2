# ClientFlow 1.3 — fresh installation from a canonical runtime release

## Normal kundeinstallation

Den normale brugerrejse følger legacy 1.1.19's to synlige faser, men med V2's fail-closed release- og enrollment-grænser under overfladen. Det repo-ejede USB-bootstrap opretter først **01 Klient klargøring**. Kontorfasen etablerer netværk, bekræfter klientnavn, opretter den faste `clientflow-kiosk` og `cfadmin`, lader kontoret definere `cfadmin`-password direkte på TTY, klargør GDM-autologin til kiosk, opretter **02 Aktiver ClientFlow** på kiosk-skrivebordet og giver kun kiosk en midlertidig passwordfri ret til den eksakte root-ejede aktiveringshelper uden argumenter. Før reboot slettes alle gemte WiFi/Ethernet/GSM/CDMA/VPN/WireGuard-profiler og hele factory-handoff'et valideres fail-closed. USB-mediet indeholder fortsat ingen `latest`/`stable` release-authority, client secret eller backend-enrollment authority.

Hos kunden lander maskinen direkte i `clientflow-kiosk`, og **02 Aktiver ClientFlow** åbnes én gang uden sudo-passwordprompt. Rækkefølgen er kundenetværk, lokation og derefter den formatterede `CF-____-____-____` kode. Helperen henter internt den durable exact release-binding og signerede fresh-install authorization, downloader den exact approved bundle med synlig fremdrift, verificerer SHA-256/størrelse samt embedded installer og sender one-time authorities til canonical installer over stdin. Den canonical installer accepterer kun de allerede eksisterende menneskelige konti, når den root-ejede schema-2 factory-state er markeret `handoff_ready` og konto-kontrakten kan genvalideres. Kunden bliver aldrig bedt om at vælge eller kende `cfadmin`-password.

Når `pending_manual_activation` er durable, fjerner helperen straks den midlertidige activation-sudoers-ret, trust-helperen og **02**-ikonet, genmaterialiserer den minimale canonical GDM/AccountsService kiosk-login-baseline fra den staged runtime, enable'r `clientflow-first-activation.service` og tilbyder den anden brugerbekræftede genstart. Klienten forbliver fail-closed og backend-`pending`. Når en superadmin efterfølgende godkender præcis klienten, kalder waiteren automatisk den immutable staged canonical `clientflow_release activate`; den re-beviser backend approval før lokal runtime-mutation. Kunden skal **ikke** åbne Aktiver ClientFlow igen efter godkendelsen.

En definitiv pre-commit 4xx fra den første consuming claim rydder canonical installerens minimale preclaim-state, hvorefter kun CF-koden indtastes igen. En tvetydig transport/5xx bevarer derimod resume-materialet, fordi backend kan have committed receipt. Wrapperen bevarer i det tilfælde den allerede verificerede exact bundle root-only og genoptager samme install/release-binding uden at kræve den eventuelt allerede konsumerede kode.

De efterfølgende manuelle bootstrap-trin i dette dokument er engineering/release-verification af samme trust boundary, ikke normal kunde-UX.

## Sikkerhedsstatus

ClientFlow 1.3.1 bruger en **keyless release-model**. Der oprettes, gemmes eller anvendes ingen privat eller offentlig release-signeringsnøgle. En normal build er en reproducerbar, verificeret release candidate med `deployable: false`. Kun en separat manuel godkendelsesgate kan producere en `deployable: true`-bundle.

Ingen fysisk installation må ske, før en konkret pilotklient er udpeget og installationen er særskilt godkendt.

ClientFlow 1.3.0 er den fysisk godkendte historiske bootstrap-baseline for den stabile, uprivilegerede updater, men den approved 1.3.0-release indeholder ikke den senere privilegerede update-controller. ClientFlow 1.3.1 er derfor den nye canonical **fresh-install bootstrap-baseline** med hele controller-kæden indbygget. 1.3.1 må ikke autoriseres som in-place update fra 1.3.0. Den canonical in-place update-kæde bevises fra en fresh-installeret 1.3.1-klient til en senere release, som eksplicit tillader `min_current_version: 1.3.1`. Pre-1.3.1 installationer skal installeres fresh i denne kæde.

## Forudsætninger for en senere godkendt installation

- Ny Ubuntu Desktop LTS 26.04 `amd64`-installation.
- Ubuntu-installationens eksisterende normale bootstrap-bruger bruges kun til den betroede kontor-/factory-session og registreres som den eksakte midlertidige bruger, der først må fjernes efter sund first activation. **01 Klient klargøring** opretter `clientflow-kiosk` og `cfadmin` før kundeoverdragelsen. Kioskbrugeren må ikke være medlem af sudo/adm/admin/wheel/lpadmin/lxd. `cfadmin` får sudo og et password, som kontoroperatøren indtaster interaktivt; passwordet gemmes ikke i ClientFlow-state eller argv.
- Ingen eksisterende ClientFlow-filer, systemd-units, Linux-brugere eller state.
- Godkendt keyless bundle med `deployable: true`, gyldig `release_approval`, SHA-256-integritetsmetadata og monoton release sequence.
- Den eksakte SHA-256 for **hele** den godkendte bundle skal være kendt via den godkendte releaseproces, før nogen installer-kode køres.
- Manifest schema 8 kræver, at den godkendte bundle fysisk indeholder fresh-installerens eksakte bytes og binder dem via `fresh_installer` filnavn/størrelse/SHA-256. Der findes ingen separat installer-path authority.
- Gyldig one-time enrollmentkode og HTTPS-forbindelse til backend.
- Eventuel privat CA leveres som PEM og kopieres til `/etc/clientflow/tls/ca.pem`.

## Fresh-install flow

1. Kør den canonical host-bootstrap i **samme shell** som den genererede fresh-install download-handoff. Genbrug handoffens allerede eksporterede `BUNDLE` og `APPROVED_BUNDLE_SHA256`; de må ikke indtastes manuelt igen. Bootstrap åbner approved bundle-pathen én gang, verificerer den åbne filidentitet mod den pinned whole-bundle SHA-256 og udtrækker installer-memberen fra **samme åbne bundle**. Materialisér både bundle og installer som root-owned private copies under `/run`. En bootstrap-fejl må ikke lukke den interaktive shell, fordi de transient enrollment-authorities skal bevares til exact retry/diagnose. Se `CLIENTFLOW_RELEASE_PROCEDURE.md` for den canonical blok.

2. Kør derefter kun den private root-owned installer-copy i Python isolated mode og verificér den private bundle-copy gennem installerens egen release-parser:

   ```bash
   sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" verify \
     --bundle "$BOOTSTRAP_BUNDLE" \
     --expected-bundle-sha256 "$APPROVED_BUNDLE_SHA256"
   ```

3. Kør `install` som root med **samme private bootstrap-filer**, bundle-SHA-256, backend-origin, enrollmentkode og kioskbruger:

   ```bash
   printf '%s\n%s\n' "$ENROLLMENT_CODE" "$FRESH_INSTALL_AUTHORIZATION" |
     sudo /usr/bin/python3 -I "$BOOTSTRAP_INSTALLER" install \
       --bundle "$BOOTSTRAP_BUNDLE" \
       --expected-bundle-sha256 "$APPROVED_BUNDLE_SHA256" \
       --backend-url https://<backend-origin> \
       --fresh-install-authority-stdin \
       --kiosk-user clientflow-kiosk
   ```

4. Installeren afviser alle eksisterende ClientFlow-spor, bortset fra de to canonical menneskelige konti og den midlertidige activation-sudoers-fil, når en sikker root-ejet schema-2 factory-state eksplicit beviser `handoff_ready`. Alle andre eksisterende ClientFlow-spor afvises fortsat. En geninstallation kræver den separate wipe-procedure med eksakt destruktiv bekræftelse.
5. Hele bundlens SHA-256 verificeres før bundlefortolkning. Derefter verificeres manifest-schema, produkt, `runtime_release`, `fresh_install` install-mode, deployable-gate, keyless release approval, payloadstørrelse/-SHA-256, arkivstier, dubletter, links, specialfiler og komplet offline runtime.
6. Releasen stages i `/opt/clientflow/releases/<release-id>` og gøres immutable.
7. Separate sysusers, kataloger og systemd-definitioner materialiseres, men `clientflow.target` forbliver disabled og inaktiv.
8. Installeren genererer en lokal RSA 3072-**systemkrypteringsnøgle** til enrollment. Det er ikke en release-signeringsnøgle.
9. I normal USB-flow er `clientflow-kiosk` og `cfadmin` allerede factory-provisioneret. Installeren genvaliderer den eksakte konto-kontrakt efter claim og spørger ikke kunden om `cfadmin`-password. Den separate engineering/direct-install sti uden factory-state kan fortsat provisionere kontiene efter claim for kompatibilitet.
10. Seks domænecredentials skrives separat for status, display, livestream, Remote Desktop, terminal og system.
11. En eventuel privat CA kopieres til den root-ejede ClientFlow-konfiguration og genbruges ved resume; installationen er ikke afhængig af den oprindelige inputfil efter første sikre kopi.
12. Standardkonfiguration, root-grant-verifikation og credentials valideres med sikre filrettigheder.
13. Installationen stopper ved status `pending_manual_activation`.
14. Den stabile updater-PYZ og dens systemd-definitioner er materialiseret, men `clientflow-updater.timer` skal være eksplicit `disabled` og `inactive` gennem hele pending-fasen. Backend update-auth forbliver fail-closed for den pending klient, og klienten må derfor ikke poll'e update-plane før godkendt first activation.
15. Efter durable `pending_manual_activation` materialiserer den ydre **02 Aktiver ClientFlow**-helper kun den minimale GDM/AccountsService login-baseline fra den staged runtime, enable'r den snævre first-activation waiter og tilbyder derefter én brugerbekræftet reboot. Rebootkommandoen bruger `systemctl --no-block --ignore-inhibitors reboot`, timeout 10 sekunder og aldrig `--force`. Rebootet etablerer den kiosk-Wayland-session, som Display readiness kræver; det aktiverer ikke releasen og starter ikke ClientFlow-runtime.

Der sker **ingen runtime-aktivering før backend-godkendelse**, ingen åbning af Terminal eller Remote Desktop, ingen start af en livestream og ingen updater-polling i `pending_manual_activation`. Waiteren må kun forsøge den canonical staged activation, og denne gate fejler lukket, indtil backend approval-proof er gyldigt.

Hvis `install` genkøres som recovery, er det kun gyldigt så længe release-state stadig er pre-activation. En committed `activation_intent`, et aktivt release-ID eller et active-symlink afviser fresh-install resume før updater/systemd-mutation; derefter bruges activation/update-recovery i stedet. Normal wrapper-resume anvender den samme root-only cached exact bundle og samme immutable release-binding; den spørger ikke efter en one-time kode, der kan være blevet consumed af en tvetydig claim.

## Backend-godkendelse og canonical first activation

Aktivering er fortsat et separat sikkerhedstrin. Efter claim står den nye klient som backend-`pending`; en superadmin skal først godkende præcis denne klient via den eksisterende backend approval-flow. First activation beviser derefter fail-closed backend-godkendelsen med installationens allerede provisionerede `status` credential, før active-symlink, systemd-definitioner eller services må ændres. Gate-status afgøres fra den durable release-state, ikke fra active-symlinket: hvis first activation crashes efter symlink-swap men før `active_release_id` er committed, skal et activation-resume derfor bevise backend approval igen før yderligere lokal mutation.

I normal kunde-UX er det `clientflow-first-activation.service`, som efter godkendelsen kalder den staged canonical release-CLI med exact release-ID og immutable approval-reference fra root-owned pending state. Operatøren skal ikke klikke **Aktiver ClientFlow** igen. Engineering-verifikation kan bruge den tilsvarende staged invocation fra `CLIENTFLOW_RELEASE_PROCEDURE.md`. Approval-reference er fortsat en kontrol mod artifactets provenance og er ikke fri audit-tekst.


Staging gemmer bundle SHA-256/size, candidate SHA-256, source commit og release-approval reference i root-ejet release-state. Aktivering afvises, hvis state, staged manifest og den eksplicit forventede release-approval ikke matcher. `clientflow.target` startes under activation først som en ikke-boot-enabled runtime, og health-resultatet gemmes durably under den eksakte activation-intent, før target må enable's til næste reboot. Dermed kan et abrupt power-loss før health ikke få en uverificeret release til at autostarte. Updater-timeren forbliver disabled gennem backend approval-proof, release-swap og runtime health. Først efter grøn, durably registreret first-activation health aktiveres `clientflow-updater.timer`, så update-plane åbnes efter den lokale runtime er operationel. Fejl før dette punkt udløser automatisk rollback til staged/pending med updater-timeren disabled og inactive.

Den canonical kiosk-baseline bruger Google Chrome `--start-fullscreen` og aldrig Chrome `--kiosk`. Den håndhæver GDM autologin/Wayland, ingen idle-lock/screensaver/suspend/dim, Bluetooth off, popup-baseline for både `clientflow-kiosk` og `cfadmin` samt Europe/Copenhagen + NTP. Efter activation genhåndhæver managed timers time-integrity hourly og kiosk quick-settings kun mens den lokale `clientflow-kiosk`-session er aktiv på `seat0`. For kiosk-brugeren skjules og ACL-blokeres lokale Settings/Terminal/package/network/Bluetooth-administrationsapps, og en kiosk-user-only polkit-regel afviser privilegerede systemændringer. `cfadmin`, root og ClientFlow-domænebrugere rammes ikke; logout/user-switch bevares, så `cfadmin` fortsat kan vælges. GDM/autologin materialiseres før den kontrollerede pre-activation reboot, så kiosk-sessionen findes før activation. GDM genstartes ikke live under activation; efter grøn activation udføres fortsat én kontrolleret reboot før reconnect-validering.

## Eksplicit wipe

Wipe er ikke en skjult installerfunktion. Den kræver både en konkret begrundelse og den eksakte streng `DESTROY-CLIENTFLOW-STATE`. Proceduren må kun anvendes efter særskilt godkendelse og sletter ClientFlow-state, users, groups, units og releases.
