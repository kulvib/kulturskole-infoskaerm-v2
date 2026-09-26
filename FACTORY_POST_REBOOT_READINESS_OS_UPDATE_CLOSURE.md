# Factory post-reboot readiness + Ubuntu update closure

Branch: `fix/factory-post-reboot-readiness-and-os-update`

## Root cause

Fresh V2 enrollment became visible for manual approval immediately after the consuming backend claim. The backend therefore had no canonical proof that the customer-side reboot had actually occurred, that the canonical `clientflow-kiosk` Wayland session and preactivation GUI were running, or that the Ubuntu package manager was healthy after installation.

The preclaim host bootstrap also repaired APT/curl prerequisites but did not intentionally refresh and apply ordinary supported Ubuntu package updates.

## Implemented contract

1. Preclaim host readiness performs `apt-get update` and `apt-get -y --with-new-pkgs upgrade`.
2. `dist-upgrade` / `full-upgrade`, firmware updates and live Chrome updates are deliberately not used.
3. `dpkg --audit` and `apt-get check` must be clean.
4. Preclaim boot-id and readiness evidence are persisted in the root-owned fresh-install state.
5. After the controlled customer reboot, the activation waiter requires a different boot-id, canonical kiosk Wayland session, active preactivation GUI, clean package-manager state and no remaining `/var/run/reboot-required`.
6. The pending Status credential publishes one narrowly scoped readiness proof to `/api/client-auth/approval-readiness`; it does not receive a runtime token.
7. The proof is stored in the existing canonical `ClientDomainStatus(domain="status")` row with `observed_state="approval_ready"`. No parallel lifecycle table or schema migration is introduced.
8. Fresh V2 enrollment clients cannot pass `/api/clients/{id}/approve` until the proof is valid.
9. Control Room keeps the approve action disabled and shows `Afventer reboot` until `approval_ready_at` is projected from the canonical Status row.
10. Runtime Status/Display/System credentials remain fail-closed until explicit human approval.

## Chrome

Chrome remains immutable/release-owned. This package does not add Google's repository, `dl.google.com`, or a live "latest Chrome" install path.

## Scope exclusions

No Livestream, Terminal or Remote Desktop runtime behavior is changed.
