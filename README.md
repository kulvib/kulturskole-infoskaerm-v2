# ClientFlow – fresh Livestream foundation

Dette repository er et nyt udgangspunkt for Infoskærm. Det implementerer **kun Livestream** mod den faktiske ClientFlow **1.2.0 seq-1200** klientkontrakt.

Det gamle 1.1.x-flow, `pending_chrome_action`, viewer-leases, gammel HLS-signalling og compatibility aliases er ikke med.

## Arkitektur

```text
Control Room (samme FastAPI service)
        |
        v
Livestream API
        |
        +--> client_command (leased FIFO queue)
        |       |
        |       v
        |   ClientFlow 1.2 livestream-agent
        |       |
        |       v
        |   local livestream broker
        |       |
        |       v
        |   FFmpeg producer + uploader
        |       |
        |       v
        +<-- generation-owned HLS upload
        |
        +--> authenticated HLS playback
```

Backend ejer **viewer-lifecycle, intent, command lease, generation identity og media health**. Ubuntu ejer **desired state, broker og process lifecycle**. Browseren rapporterer kun viewer-presence og afspiller HLS; backend afgør altid Start/Stop.

## ClientFlow 1.2-kontrakt

Klienten forventer disse endpoints:

- `POST /api/client-auth/token`
- `POST /api/livestream-agent/clients/{id}/commands/claim`
- `POST /api/livestream-agent/clients/{id}/commands/{command_id}/renew`
- `POST /api/livestream-agent/clients/{id}/commands/{command_id}/complete`
- `POST /api/livestream-agent/clients/{id}/commands/{command_id}/fail`
- `PUT /api/livestream-agent/clients/{id}/status`
- `POST /api/livestream-agent/clients/{id}/generations/{generation_id}/started`
- `POST /api/livestream-agent/clients/{id}/generations/{generation_id}/stopped`
- `PUT /api/livestream-agent/clients/{id}/generations/{generation_id}/files/{filename}`

Understøttede Livestream commands er `start`, `restart`, `reset_generation` og `stop`.

## Datamodel

Otte tabeller:

1. `organization`
2. `user_account`
3. `client`
4. `client_domain_credential`
5. `client_command`
6. `client_domain_status`
7. `livestream_generation`
8. `livestream_viewer`

HLS-filer er transient media og ligger ikke i databasen.


## Viewer-ejet lifecycle

Livestream har ingen normal Start/Stop-knap i Control Room. Lifecycle følger aktive viewers:

- første viewer åbner Livestream → automatisk `start`
- heartbeat hvert `VIEWER_HEARTBEAT_SECONDS` (default 10 s)
- viewer-lease udløber efter `VIEWER_LEASE_SECONDS` (default 30 s)
- sidste viewer væk → `VIEWER_STOP_GRACE_SECONDS` (default 30 s) → automatisk `stop`
- vender en viewer tilbage inden grace, fortsætter samme generation uden Stop/Start
- flere viewers deler samme generation; streamen stopper først, når sidste viewer er væk
- skjult fane, klientskift, logout og `pagehide` sender viewer-leave
- browsercrash/netværkstab håndteres af lease-expiry
- media-watchdog laver kun `reset_generation`, mens mindst én viewer er aktiv

Backend kører en lille DB-baseret reconcile-loop hvert `VIEWER_RECONCILE_INTERVAL_SECONDS` (default 5 s). Viewer-data er transient lifecycle-state; HLS er fortsat transient media på disk.

## Media health

ClientFlow 1.2 kan rapportere producer=`running`, selv før der findes brugbare segmenter. Derfor bruger backend **faktiske HLS uploads** som health-signal.

Hvis en aktiv generation ikke har haft uploadprogression inden for `MEDIA_STALE_SECONDS` (default 45 s), opretter backend én ny generation og sender `reset_generation`. Browseren må ikke genstarte Ubuntu-processer.

## Lokal udvikling

Opret miljøvariabler fra `backend/.env.example`, opret en tom PostgreSQL-database og kør:

```bash
cd backend
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Første startup opretter admin-brugeren fra `ADMIN_EMAIL` + `ADMIN_PASSWORD`, hvis databasen endnu ikke har brugere.

## Render – frisk staging

`render.yaml` opretter én Python 3.13.14 web service og én **frisk** PostgreSQL-database. Deploy dette som **staging først**. Tilslut ikke den gamle produktionsdatabase til denne baseline.

Vigtigt under Livestream-isolation: ClientFlow 1.2 har credential pr. domæne. Peg derfor kun Ubuntu-maskinens `livestream.json` på denne staging-backend. Display, Terminal, Remote Desktop og System kan fortsætte mod deres eksisterende backend, indtil deres tur kommer.

I Control Room:

1. Opret klienten.
2. Vælg **Nyt Livestream credential**.
3. Download `livestream.json`.
4. Installer kun denne fil på Ubuntu som Livestream credential.
5. Genstart kun `clientflow-livestream-agent.service` og `clientflow-livestream-uploader.service`.

De konkrete Ubuntu-kommandoer gives først i den fysiske testfase.

## Bevidst ikke med

- Terminal
- Remote Desktop
- Display management
- System/update agent
- Redis
- WebSockets
- React/Node build
- gammel 1.1.x-klientkode
- gammel database/migrationshistorik
- browserstyret producer-lifecycle uden backend-authoritet

Fælles control-plane kan udvides senere, men kun når næste funktion behandles.
