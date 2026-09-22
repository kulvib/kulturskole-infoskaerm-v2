# Pre-1226 update-plane idle request consolidation

## Scope

This package reduces the always-on ClientFlow update-control-plane cost without changing the updater timer, deployment detection cadence, deployment state machine, artifact verification, activation authority, DPoP/private-key security, or UI behavior.

The fresh baseline remains ClientFlow 1.3.24 / release sequence 1225. Release 1.3.25 / sequence 1226 remains paused.

## Repository-proven root cause

`clientflow-updater.timer` runs the stable updater once per minute and `clientflow-updater.service` starts `clientflow-update-controller.service` on success. In the idle case both processes historically performed the same two-request discovery sequence:

1. `POST /api/clientflow-update/token`
2. `GET /api/clientflow-update/deployments/active`

Before this package, each token request loaded the update credential and Client in two separate SELECTs. The protected-resource GET repeated those two reads, consumed another DPoP replay row, updated `last_used_at` again, and finally selected the active deployment.

The token endpoint also called expired replay cleanup once for the client assertion and once again for the DPoP proof inside the same transaction.

No deployment data required the second HTTP round-trip: the token endpoint has already authenticated the exact asymmetric update identity, verified Client lifecycle, normalized scopes, validated a fresh DPoP proof, and consumed the token-request replay identifiers.

## Implementation

### Optional active-deployment bootstrap

`UpdateTokenRequest` gains the optional boolean `include_active_deployment`.

When it is true **and** the normalized token scopes contain `deployment:read`, the token response includes:

- `active_deployment_included=true`
- `active_deployment=<canonical ClientFlowDeploymentRead or null>`

The response is an explicit ACK. A new client talking to an older backend sends the unknown optional request field, receives no ACK, and immediately falls back to the historical authenticated `GET /deployments/active`. Old clients talking to the new backend continue using the old two-request flow unchanged.

Both the unprivileged stable updater and the privileged update controller use the bootstrap when acknowledged. Their later reconciliation/event paths keep the existing protected-resource requests because those paths require fresh state after mutations.

### Credential + Client JOIN

Both client-assertion authentication and DPoP protected-resource authentication now load `ClientFlowUpdateCredential` and its Client in one outer JOIN. Existing error distinctions and lifecycle checks remain intact:

- missing/revoked credential;
- unsupported credential algorithm;
- missing/deleted/unapproved Client;
- token client/key mismatch;
- scope checks;
- DPoP key binding and `ath` validation.

There is no cross-request credential or lifecycle cache.

### One replay cleanup per token transaction

The token request still stores **both** unique replay identities:

- client-assertion JTI;
- token-request DPoP JTI.

Expired replay rows are now cleaned once immediately before the first replay insertion rather than issuing the same global DELETE twice in one transaction. The unique replay constraint and both replay inserts remain unchanged.

The current DPoP standard requires a fresh proof per HTTP request and allows servers to retain proof JTIs for replay prevention. This package removes an HTTP request; it does not reuse a proof across requests or weaken the remaining proof checks. HTTPS remains mandatory for the transport.

## Idle database/request budget

Repository-level statement model per online client/minute, considering the normal updater run plus its successful root-controller follow-up:

### Before

Per process:

- 2 HTTP requests;
- 5 SELECTs (token credential + Client, resource credential + Client + active deployment);
- 3 replay cleanup DELETE statements;
- 3 replay INSERTs;
- 2 credential `last_used_at` updates.

Across updater + controller:

- 4 HTTP requests/minute;
- 10 SELECTs/minute;
- 6 replay cleanup DELETEs/minute;
- 6 replay INSERTs/minute;
- 4 credential updates/minute.

### After

Per process on a new backend:

- 1 HTTP request;
- 2 SELECTs (joined credential+Client + active deployment);
- 1 replay cleanup DELETE;
- 2 replay INSERTs (assertion + DPoP, both still single-use);
- 1 credential update.

Across updater + controller:

- 2 HTTP requests/minute (**50% reduction**);
- 4 SELECTs/minute (**60% reduction**);
- 2 replay cleanup DELETEs/minute (**67% reduction**);
- 4 replay INSERTs/minute (**33% reduction**);
- 2 credential updates/minute (**50% reduction**).

This is a repository SQL/request budget, not a claim that Neon bills per statement. Neon bills primarily on compute usage, storage, and related usage dimensions; fewer always-on requests and statements reduce avoidable compute/write pressure.

## Preserved invariants

This package does **not** change:

- one-minute updater timer cadence;
- deployment detection latency;
- update credential revocation/rotation semantics;
- Client approval/deletion checks;
- token scopes or token TTL;
- DPoP `htm`, `htu`, `ath`, key binding, timestamp or JTI checks;
- client-assertion signature/audience/issuer/JTI checks;
- artifact authorization/download verification;
- updater/controller privilege separation;
- deployment state transitions;
- release/catalog identity;
- frontend/UI behavior.

## External best-practice boundary

The code changes above are justified by repository behavior. External references only support the security/cost framing:

- RFC 9449 requires a unique DPoP proof for each HTTP request and describes JTI retention for replay detection. Removing a redundant HTTP request removes the need for a second proof; it does not permit proof reuse.
- Neon's usage model is compute/storage based rather than a fixed per-query fee. Reducing always-on SQL and write activity is therefore an efficiency measure aimed at lowering compute pressure rather than a claim of per-statement billing.

## Gates

Local dependency-independent gates must include:

- full `scripts/tests`;
- updater/controller crypto and source-contract suites;
- transport tests proving one-request idle bootstrap and old-backend fallback;
- Python compilation of all changed Python files.

GitHub CI remains authoritative for the executable SQLModel database-cost tests. The new test requires the idle bootstrap token transaction to stay at exactly two SELECTs and one expired-replay cleanup DELETE.
