CLIENTFLOW USB · START HER

1. Start Ubuntu med den normale installationsbruger.
2. Åbn USB-mediet.
3. Kør 01_START_CLIENTFLOW_USB.sh i en terminal.
4. USB-flowet verificerer sine canonical bootstrap-filer, sikrer netværk og opretter:
   01 Klient klargøring
5. Klik derefter på 01 Klient klargøring og følg flowet.

Vigtigt:
- Release vælges aldrig fra USB-mediet.
- Exact ClientFlow release bindes først af den gyldige CF-kode i fase 2.
- USB-payloaden må ikke redigeres manuelt; SHA-256-kontrollen vil afvise ændrede filer.

Distributionskontrol:
- Hele ZIP-filens SHA-256 fra den godkendte bygge-/handoff-proces er den eksterne trust anchor.
- USB_SHA256SUMS.txt kontrollerer alle start-/payloadfiler efter udpakning; PAYLOAD_SHA256SUMS.txt kontrolleres også særskilt før installation.
