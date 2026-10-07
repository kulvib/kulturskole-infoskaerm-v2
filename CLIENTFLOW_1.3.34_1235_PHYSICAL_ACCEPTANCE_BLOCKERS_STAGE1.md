# ClientFlow 1.3.34 / sequence 1235 · physical-acceptance blockers · stage 1

Status: staged source identity only. Not source-frozen, not built, not approved, not published and not catalog-promoted.

The physically rejected immutable 1.3.33/1234 release remains the only promoted fresh-install catalog entry while the next source identity is prepared.

Stage 1 closes source-proven failures that do not require another visit to the physical client:

- Control Room realtime wait now sends the short-lived realtime capability directly instead of routing it through the ordinary browser-session `apiFetch()` wrapper, which previously replaced its Authorization header and caused repeated HTTP 401 responses in both ClientList and ClientDetails.
- Ubuntu update projection now carries the exact canonical System command id. The frontend correlates local optimistic state with that id and does not reuse terminal status, error text or timestamps from an older update command while a new command is waiting for the hot projection.
- Kiosk-lockdown UI distinguishes desired state from observed state. It may only label lockdown `Aktiv` after the client reports canonical `applied`; desired=true with unknown/unconfirmed observation is shown as `Ikke bekræftet`.
- The local kiosk GUI removes the close affordance and consumes GTK4 `close-request`, while the existing Display runtime process supervisor remains responsible for restarting the GUI if it exits for another reason.

Still open before 1.3.34/1235 source freeze:

- physical root-cause evidence for the Ubuntu update helper failure observed on client 54;
- physical root-cause evidence for kiosk-lockdown not being enforced locally despite backend desired=true;
- full clean Ubuntu 26.04 physical retest after those runtime causes are fixed.
