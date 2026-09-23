CLIENTFLOW USB · START HER

PlanIQ Flow / ClientFlow

1. Start Ubuntu med den normale installationsbruger.
2. Åbn USB-mediet i Filer.
3. Dobbeltklik på "Start ClientFlow.EXE".
4. Den grafiske filstarter åbner en terminal og kalder den eksisterende canonical:
   01_START_CLIENTFLOW_USB.sh
5. USB-flowet verificerer sine canonical start- og bootstrap-filer, sikrer netværk
   og opretter:
   01 Klient klargøring
6. Klik derefter på 01 Klient klargøring på skrivebordet og følg flowet.

PlanIQ Flow-branding:
- "PlanIQ Flow.png" på USB-roden er det originale, uændrede PlanIQ Flow-logo fra Flow-repoet.
- Logoet er branding omkring USB-startoplevelsen; det bruges ikke som en ny
  bootstrap- eller sikkerhedsautoritet.

Teknisk:
- "Start ClientFlow.EXE" er et Linux amd64 ELF-program, ikke et Windows-program.
- .EXE-suffikset er bevidst for FAT32/vfat showexec-kompatibilitet på Ubuntu.
- Launcheren indeholder ingen sudo-, release-, download-, checksum- eller
  installationslogik. Den starter kun terminalen med 01_START_CLIENTFLOW_USB.sh.
- Hvis den grafiske launcher mod forventning ikke kan åbnes, kan samme canonical
  entrypoint startes manuelt fra USB-mappen med:

  bash 01_START_CLIENTFLOW_USB.sh

Vigtigt:
- Release vælges aldrig fra USB-mediet.
- Exact ClientFlow release bindes først af den gyldige CF-kode i fase 2.
- USB-payloaden må ikke redigeres manuelt; SHA-256-kontrollen vil afvise ændrede filer.

Distributionskontrol:
- Hele ZIP-filens SHA-256 fra den godkendte bygge-/handoff-proces er den eksterne trust anchor.
- USB_SHA256SUMS.txt kontrollerer alle distribuerede start-/branding-/payloadfiler efter udpakning.
- PAYLOAD_SHA256SUMS.txt kontrolleres også særskilt før installation.
