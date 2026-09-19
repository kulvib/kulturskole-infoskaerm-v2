# ClientFlow V2 factory → customer handoff closure

## Scope

This change restores the physically proven legacy 1.1.19 customer handoff while preserving V2 exact-release, consuming-claim and approval gates. Livestream, Terminal and Remote Desktop runtime domains are unchanged.

## Contract

After **01 Klient klargøring** and its confirmed reboot, the machine is a shipping-ready appliance state:

- `clientflow-kiosk` and `cfadmin` already exist;
- `cfadmin` password was chosen on the trusted office side and is never stored in ClientFlow state;
- kiosk has no sudo/adm/admin/wheel/lpadmin/lxd membership;
- GDM autologin points to `clientflow-kiosk` on Ubuntu Wayland;
- **02 Aktiver ClientFlow** is on the kiosk desktop;
- kiosk can run only the exact SHA-256-bound root-owned fresh-install helper, with no arguments, through `sudo -n`;
- all saved WiFi/Ethernet/GSM/CDMA/VPN/WireGuard NetworkManager profiles have been removed and rechecked;
- no ClientFlow client secret, enrollment credential or active runtime exists.

The canonical installer accepts these pre-existing human accounts only when the private root-owned schema-2 factory state is `handoff_ready=true`, matches the explicit client identity and canonical account names, and the account contract revalidates. Every other pre-existing ClientFlow trace remains a fresh-install conflict.

After the customer flow reaches durable `pending_manual_activation`, the temporary activation sudoers file, trust helper and **02** desktop icon are removed before the pre-activation reboot. The staged release's existing legacy-layout local GUI is then exposed through a temporary bootstrap-owned `clientflow-preactivation-gui.service`. It runs as `clientflow-kiosk` in an explicit status-only mode, shows `Registreret – afventer godkendelse`, keeps Start/Stop kiosk disabled, exposes no administrator-switch action, and starts no ClientFlow runtime domain. The service conflicts with `clientflow.target`, so backend-approved activation replaces it with the normal release-owned runtime GUI rather than running two GUI lifecycles in parallel.

## Terminal UX

The operator-visible flow again provides legacy-style status/help: cable-first network explanation, Ethernet/NetworkManager/IP status, explicit phase/OK/warning lines, download byte/percentage progress, and ordinary `dpkg`/`apt` output when host package repair is actually required. Passwords, CF authorization, client secrets and credentials are never printed.

## Security notes

The customer activation sudoers entry is command-specific, SHA-256-bound and uses the sudoers empty argument string (`""`) so no command-line arguments are permitted. The capability is temporary and removed only after durable pending state, preserving safe crash/resume before that point.
