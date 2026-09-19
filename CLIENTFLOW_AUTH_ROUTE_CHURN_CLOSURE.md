# ClientFlow auth route-churn closure

Date: 2026-09-19

## Evidence

After direct browser -> backend transport removed the Render static-site rewrite bottleneck, whole-repo review found that `AuthProvider` still keyed its boot effect to `location.pathname`.

On every internal route change this caused the provider to:

1. set global auth `loading=true`;
2. call `performBootRefresh()` (normally a no-op while the in-memory access token is valid);
3. call `GET /api/auth/me` against the database;
4. set `loading=false` again.

`ProtectedRoute` then ran its own `GET /api/auth/me` validation when auth loading completed. The backend already revalidates the bearer principal against the current `User` row on protected API requests, including `is_active` and `token_version`.

This made route navigation do duplicate database-backed auth validation and could blank the protected route while `loading` toggled.

## Fix

- `AuthProvider` captures only the initial browser pathname and runs boot/session restoration for that initial entry route. It no longer reruns boot because React Router changes pathname.
- `ProtectedRoute` is now a pure UI/role/password-change gate over AuthProvider state and performs no network request of its own.
- Existing security/session paths remain unchanged:
  - initial boot restores the HttpOnly refresh session and fetches `/api/auth/me` once;
  - every protected backend API request validates the current user row and token version;
  - API 401 handling keeps the single-flight refresh + retry path;
  - explicit idle-session continuation still performs server-side refresh validation;
  - logout/revocation/password/token-version behaviour is unchanged.

## Cost/performance effect

Internal navigation no longer creates route-churn `/api/auth/me` reads. This reduces Neon-backed requests and removes the global loading toggle caused solely by navigating between already-authenticated pages.

No database model, backend authorization rule, refresh-token policy, role rule, API route, or release-runtime code changed.

## Tests

`frontend/tests/authRouteChurnContract.test.mjs` locks the new ownership contract and verifies that 401 refresh plus explicit idle-session validation remain present.
