# ClientFlow database cost / polling efficiency closure

Status: source candidate after canonical main `3575fe18e93818ee48e7bef388472b85fb39ab66`.

## Scope

This package reduces always-on PostgreSQL/Neon work without weakening the
ClientFlow domain, approval, credential or liveness authorities.

It deliberately does **not** change:

- the reviewed 15-second shared Status/Display/System status-report cadence;
- the 120-second shared-domain presence timeout;
- Livestream, Terminal or Remote Desktop implementation;
- database pool size/recycle/pre-ping policy;
- release/catalog identity.

## Proven root causes

### 1. V2 command consumers polled faster than legacy

Legacy 1.1.19 uses `BACKEND_POLL_INTERVAL=5` for its backend config/action loop.
V2's shared Display/System `QueueAgent` default was 2 seconds.

Because both V2 command agents poll continuously, an idle approved client sent
60 command-claim requests/minute before this package.

The default command cadence is now five seconds, matching the proven legacy
backend/action cadence.  The separately reviewed 15-second liveness heartbeat
remains unchanged.

### 2. Every shared-agent token validation loaded credential and client separately

`require_shared_agent_token()` and initial shared credential authentication each
loaded `ClientDomainCredential` and `Client` with separate ORM lookups.

They now enforce the same credential/client/domain/revocation/token-version/
approval/deletion predicates in one joined SQL query.

No authorization result is cached.  Revocation and client approval therefore
remain database-authoritative on every request.

### 3. An empty command claim queried the active queue twice

The claim path first selected queued/claimed rows for reconciliation and then
issued a second command query for the candidate. Display additionally loaded
the Display status row before it knew whether any command existed.

The queue is now read and locked once, reconciled in memory, and the candidate
is selected from those same locked rows. The Display capability row is read
only when an active Display command exists. The existing fail-closed capability
gate remains unchanged for real commands.

### 4. Hidden Control Room tabs continued database polling

The client list (2 s), client detail chrome/status projection (1 s), superadmin
active-deployment check (2.5 s) and selected config/diagnostics background
refreshes continued while the document was hidden.

Those always-on/read-only pollers now skip network/database reads while
`document.visibilityState == "hidden"`. Client list already refreshes
immediately on focus/visibility return; the one-second detail loop resumes
within its next normal tick. Active mutation confirmation loops are intentionally
not paused by this package.

## Idle shared command budget

Ignoring SQLAlchemy connection liveness pings and uncommon command/status side
effects, the known idle command-claim SELECT budget changes from approximately:

- before: Display `30 * 5` + System `30 * 4` = 270 SELECTs/min/client;
- after: Display `12 * 2` + System `12 * 2` = 48 SELECTs/min/client.

That is an approximately 82% reduction in the known idle command-claim SELECT
round-trips. Shared status reports also save one authorization SELECT per report
because credential/client validation is joined.

This is a code-level round-trip budget, not a claim that Neon bills a fixed
amount per SQL query. Neon usage is compute/storage based; fewer always-on
queries reduce compute work and connection pressure.

## Database setup boundary

The repository cannot prove whether Render's secret `DATABASE_URL` uses Neon's
direct or pooled hostname. That must be checked in the deployed Render/Neon
configuration. No secret or hostname is committed by this closure.

The existing SQLAlchemy QueuePool remains intentionally unchanged until actual
production pool/latency metrics justify a different size. Database tuning must
be based on measured `Server-Timing`, pool status, Neon metrics and PostgreSQL
query plans rather than arbitrary pool/index changes.
