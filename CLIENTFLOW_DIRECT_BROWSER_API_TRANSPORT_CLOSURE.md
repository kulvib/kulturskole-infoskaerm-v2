# ClientFlow direct browser API transport closure

Date: 2026-09-19

## Evidence

Production browser measurements on the deployed merge commit showed that the Render
Static Site rewrite dominated request latency:

- `/version` median: direct backend 57.2 ms; frontend rewrite 422.9 ms; +365.7 ms.
- `/health/db` median: direct backend 68.3 ms; frontend rewrite 633.6 ms; +565.3 ms.
- Authenticated `/chrome-status`: 427.6 ms wall while application time was 24.61 ms
  and database time 14.82 ms (6 statements, 1 checkout).
- Authenticated `/clients/`: 840.9 ms wall while application time was 28.18 ms
  and database time 16.15 ms (6 statements, 1 checkout).

The measured bottleneck is therefore the browser -> Render Static Site -> public
backend rewrite path, not PostgreSQL execution or backend processing.

## Canonical change

1. Production `VITE_API_URL` is `https://api.display.planiq.dk`.
2. Ordinary API/HLS/file traffic uses the public backend directly.
3. Login, refresh and logout remain on same-origin `/api/auth/*`.
4. The existing `/api/*` static-site rewrite remains as auth/compatibility fallback.
5. Existing host-only HttpOnly refresh cookies therefore remain valid and require no
   cookie-domain migration or forced logout.
6. Backend CORS remains restricted to explicit PlanIQ Display frontend origins and
   allows credentials/Authorization. `Server-Timing` is exposed for safe direct
   transport diagnostics.
7. WebSocket transport was already direct and is unchanged.

## Security properties preserved

- Access tokens remain in memory and are transported as Bearer tokens.
- Refresh tokens remain HttpOnly and host-only on the frontend origin.
- Refresh/login/logout continue to use `credentials: include` on same-origin.
- Direct cross-origin data requests are allowed only from configured CORS origins.
- Existing CSRF origin checks for cookie-authenticated unsafe requests are unchanged.
- No wildcard credentialed CORS policy is introduced.

## Expected effect

The change removes the measured 365-565 ms Render rewrite overhead from ordinary
browser API requests. Actual authenticated calls can incur CORS preflight when using
Authorization; browser preflight caching and direct backend RTT still make this a
materially shorter path than the measured external rewrite.

## Rollback

Set frontend `VITE_API_URL` back to an empty value and redeploy the static frontend.
The retained `/api/*` rewrite restores the previous same-origin data path without a
backend rollback.
