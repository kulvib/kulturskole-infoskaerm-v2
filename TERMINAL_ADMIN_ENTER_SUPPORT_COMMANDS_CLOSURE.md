# Terminal admin Enter + support-command closure

## Scope

This closure updates only the Control Room Terminal UX/support catalog. It does not change Terminal authentication, browser-ticket/WebSocket protocol, root broker trust boundaries, Livestream, or Remote Desktop runtime behavior.

## Admin password keyboard flow

The admin password field now handles Enter with the exact same `adminOpenDisabled` predicate used by the `Åbn Admin-terminal` button. IME composition is ignored, and no alternate authentication path is introduced.

## Support catalog

The catalog is rebuilt around current V2 authorities:

- canonical ClientFlow domain services
- Display runtime/configuration/browser state
- active immutable release and stable updater timer
- Ubuntu/dpkg/APT health and reboot-required marker
- disk, memory and uptime
- NetworkManager/IP/DNS/time/NTP/backend `/health` reachability
- current domain journal logs

Legacy repair actions that mutate package locks, reinstall Python dependencies, reset installer caches, or invoke the legacy desktop installer are intentionally not restored. Runtime OS update remains a separate System-domain operation and is not exposed as a Terminal support shortcut.
