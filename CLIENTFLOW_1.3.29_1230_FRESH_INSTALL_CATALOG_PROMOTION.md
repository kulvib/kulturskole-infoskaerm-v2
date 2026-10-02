# ClientFlow 1.3.29 / sequence 1230 — fresh-install-only catalog promotion

## Purpose

This change promotes the already approved and immutably published ClientFlow
1.3.29/1230 bytes as the canonical **fresh-install** target. It does not claim
or authorize in-place update compatibility.

The physical 1.3.28/1229 acceptance run exposed three release-blocking runtime
defects (Remote Desktop kiosk-home permissions, Browser Guard consent-overlay
cleanup and live calendar status colouring). Those fixes are included in the
1.3.29/1230 immutable bundle. The previously used physical client no longer
exists, and only clean Ubuntu installations are available now. Therefore an
authentic 1.3.28 -> 1.3.29 physical update proof cannot be produced without
manufacturing a downgrade, which is explicitly rejected as evidence.

## Immutable authority chain

- release id: `clientflow-1.3.29-seq-1230`
- source commit: `e0f0986c7c7a214d8b25d3fe3bcfb1df93149e30`
- exact-source CI: `#1185` / run `37020483780` / success
- runtime-input transport: `#13` / run `37022128292` / success
- runtime-input SHA-256: `14c5fee3193b8a8c93559643afa5bf96de910ca64233e483628aafee643021fb`
- release build: `#34` / run `37022826670` / success
- candidate SHA-256: `db998add1acefeae384bb293ece0e077faab075cf161afb9ed633dcdf3c48251`
- installer SHA-256: `eabd9d84bcfb09243ba409a77fd63ecaccb72e7af2c017b604169471f984c4c1`
- payload SHA-256: `1bb53dd490988d5ed5010125a33a47011d30fa0a72b8d3d8f1cfe7d544f242c0`
- approval: `#17` / run `37024325019` / success
- approval reference: `clientflow-1.3.29-seq-1230/e0f0986c7c7a214d8b25d3fe3bcfb1df93149e30/manual-approval`
- approved transport tag: `clientflow-1.3.29-1230-approved-transport`
- approved bundle size: `224153600`
- approved bundle SHA-256: `aa0fc65730b2b7be925eca33f0a2028af675f42e3e2826bc1bd7533e43a94b40`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.29-seq-1230.tar`
- immutable store re-read: exact size and SHA-256 verified, `CLIENTFLOW_1_3_29_STORE_VERIFY=PASS`

Sequence 1228 remains absent because immutable 1.3.27/1228 was security-rejected
before selector promotion due CVE-2026-101918.

## Catalog authority after this change

- `catalog_sequence = 1230`
- `latest_stable = 1.3.29`
- `default_install_version = 1.3.29`
- single selected release: `clientflow-1.3.29-seq-1230`
- `installable = true`
- `install_modes = ["fresh_install"]`
- `update_allowed = false`
- rollback remains disabled
- controlled reboot remains required
- Ubuntu Desktop 26.04 LTS / amd64 / GNOME Wayland platform preflight remains mandatory
- embedded runtime Python remains `3.13.14`

The catalog does not duplicate immutable bundle hashes, source commit or approval
metadata as selector fields; those remain authority in the published artifact
and this promotion record.

## Fail-closed update boundary

`backend/service1/clientflow_releases.py` previously required every catalog
release to declare `in_place_update`, even when update evidence did not exist.
That policy is narrowed so a release may be valid for fresh installation only.
`update_allowed=true` still requires the `in_place_update` mode, and the safe
1.3.11 predecessor baseline remains mandatory whenever an in-place update mode
is declared for sequence 1212 or later.

For 1.3.29/1230, `resolve_release("1.3.29")` therefore fails closed with the
catalog block reason, while `resolve_fresh_install_release()` selects the exact
1.3.29/1230 release. This prevents Control Room from offering an update that has
not been physically proven.

The legacy update-safety regression fixture is also made explicit: when it tests
a hypothetical post-1211 in-place-capable release, it now sets
`install_modes=["fresh_install", "in_place_update"]` and `update_allowed=true`
instead of inheriting selector flags from the current catalog. This preserves
the original security assertion that an in-place-capable release may not
advertise a predecessor older than the safe 1.3.11 baseline, while allowing the
real 1.3.29 selector to remain intentionally fresh-install-only.

## Physical evidence boundary

The current clean-machine baseline has been verified on Ubuntu 26.04.1 LTS,
`amd64`, Wayland with no ClientFlow directories, accounts or units present.
That proves the machine is suitable for final clean-install acceptance; it does
not prove the 1.3.29 runtime itself.

After this selector change is merged, CI-green and deployed, the immediate next
gate is the normal fresh-client flow from canonical USB through 01 Klient
klargøring, 02 Aktiver ClientFlow, backend approval and active runtime. The
physical run must specifically verify Remote Desktop connection/file access,
Browser Guard on canonical browser start/reset/config-change paths, calendar
status colours, service health and the required 10-second display/browser
timings.

The missing 1.3.28 -> 1.3.29 in-place proof remains explicitly **UNVERIFIED**.
No future release may cite this promotion as evidence for that update path.
Python 3.13.15 also remains blocked until an authentic compatibility-bridge
update proof exists.
