# ClientFlow 1221 pre-activation reboot inhibitor fix

Date: 2026-09-13

## Physical finding

Canonical Ubuntu 26.04.1 fresh-install of approved `clientflow-1.3.20-seq-1221` reached durable `pending_manual_activation` and completed `DISPLAY_SESSION_PREPARE_OK`, but the required controlled reboot was rejected by the active GNOME session's shutdown inhibitor.

Observed systemd result:

- `Operation inhibited by "viborg4" ... gnome-session-s ... user session inhibited`
- the helper then failed with `Kunne ikke køe den kontrollerede pre-activation reboot`

Physical evidence also confirmed:

- exact 1.3.20/1221 bundle binding, approved SHA/size/source/approval;
- canonical staged release present and root-owned/read-only;
- `cfadmin` provisioned with sudo;
- `clientflow-kiosk` provisioned without sudo/adm/admin/wheel/lpadmin/lxd;
- GDM autologin and AccountsService Ubuntu session materialized correctly;
- the failure occurs only at the reboot transition.

## Root cause

`client/bootstrap/clientflow-fresh-install` queued the lifecycle reboot with:

```text
systemctl --no-block reboot
```

On the canonical Ubuntu desktop install path, the operator is necessarily still logged in while the helper completes. GNOME therefore owns a block shutdown inhibitor. `systemctl` honors that inhibitor and rejects the reboot.

The repository already uses the narrower systemd inhibitor override for controlled ClientFlow reboot authorities (`--ignore-inhibitors`) in the calendar reboot broker and system reboot broker. The fresh-install lifecycle path was inconsistent with those existing reboot contracts.

## Fix

The fresh-install helper now queues only:

```text
systemctl --no-block --ignore-inhibitors reboot
```

with a 10-second subprocess timeout.

This is deliberately **not** `--force`: normal systemd shutdown ordering remains intact; only inhibitor locks are overridden for this explicit root-authorized lifecycle transition. The durable `pending_manual_activation` and exact release-binding guards remain mandatory before the reboot can be queued.

## Release discipline

This patch does not modify `client/VERSION`, release sequence, runtime catalog, or any immutable 1.3.20/1221 release bytes. `clientflow-1.3.20-seq-1221` remains a physically failed canonical fresh-install release and is not hotfixed in place.

After this fix has passed full GitHub CI, a new source/build identity and new immutable release must be cut through the normal build, approval, publication, catalog-promotion, and clean physical verification gates.

Livestream, Terminal, and Remote Desktop implementation files are untouched.
