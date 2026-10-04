"""Post-final-reboot customer handoff acceptance gate.

The fresh installer stages a pending customer handoff immediately before its
final reboot.  This service runs from the activated runtime on the new boot and
marks the handoff accepted only after the canonical kiosk session, kiosk
lockdown, account separation and Nautilus baseline are all observable together.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import stat

from .atomic import atomic_write_json
from .kiosk_lockdown import status as lockdown_status
from .kiosk_session_policy import _active_local_kiosk_session

STATE_PATH = Path(os.getenv("CLIENTFLOW_CUSTOMER_HANDOFF_STATE", "/var/lib/clientflow/release/customer-handoff.json"))
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
NAUTILUS = Path("/usr/bin/nautilus")
KIOSK_USER = "clientflow-kiosk"
ADMIN_USER = "cfadmin"
ADMIN_GROUPS = {"sudo", "admin"}
STATE_OWNER_UID = 0


class PostFinalRebootAcceptanceError(RuntimeError):
    pass


def _read_state() -> dict[str, object] | None:
    try:
        meta = STATE_PATH.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_uid != STATE_OWNER_UID or (meta.st_mode & 0o077):
        raise PostFinalRebootAcceptanceError("Customer handoff-state har usikre ownership/permissions")
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PostFinalRebootAcceptanceError("Customer handoff-state er ugyldig") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PostFinalRebootAcceptanceError("Customer handoff-state har ukendt schema")
    return value


def _boot_id() -> str:
    try:
        value = BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise PostFinalRebootAcceptanceError("Kernel boot-id kan ikke læses") from exc
    if not value:
        raise PostFinalRebootAcceptanceError("Kernel boot-id mangler")
    return value


def _group_names(username: str) -> set[str]:
    try:
        record = pwd.getpwnam(username)
    except KeyError as exc:
        raise PostFinalRebootAcceptanceError(f"Canonical konto mangler: {username}") from exc
    import grp
    names: set[str] = set()
    for entry in grp.getgrall():
        if entry.gr_gid == record.pw_gid or username in entry.gr_mem:
            names.add(entry.gr_name)
    return names


def verify_and_accept() -> dict[str, object]:
    if os.geteuid() != 0:
        raise PostFinalRebootAcceptanceError("Post-final-reboot acceptance kræver root")
    state = _read_state()
    if state is None:
        return {"schema_version": 1, "status": "not_required"}
    if state.get("status") == "accepted":
        return state
    if state.get("status") != "awaiting_post_final_reboot_acceptance":
        raise PostFinalRebootAcceptanceError("Customer handoff-state er ikke pending acceptance")

    current_boot = _boot_id()
    previous_boot = str(state.get("pre_reboot_boot_id") or "").strip()
    if not previous_boot or current_boot == previous_boot:
        raise PostFinalRebootAcceptanceError("Final reboot er endnu ikke observeret")
    if _active_local_kiosk_session() is None:
        raise PostFinalRebootAcceptanceError("Canonical clientflow-kiosk session er endnu ikke aktiv på seat0")

    lockdown = lockdown_status()
    if (
        lockdown.get("desired") is not True
        or lockdown.get("status") != "applied"
        or not isinstance(lockdown.get("enforcement"), dict)
        or lockdown["enforcement"].get("ok") is not True
    ):
        raise PostFinalRebootAcceptanceError("Kiosk lockdown er ikke verificeret applied efter final reboot")

    kiosk_groups = _group_names(KIOSK_USER)
    if kiosk_groups & ADMIN_GROUPS:
        raise PostFinalRebootAcceptanceError("Kiosk-brugeren har administratorgruppe efter final reboot")
    admin_groups = _group_names(ADMIN_USER)
    if not (admin_groups & ADMIN_GROUPS):
        raise PostFinalRebootAcceptanceError("cfadmin mangler administratorgruppe efter final reboot")
    if not NAUTILUS.is_file() or not os.access(NAUTILUS, os.X_OK):
        raise PostFinalRebootAcceptanceError("Nautilus mangler eller er ikke eksekverbar efter final reboot")

    accepted = dict(state)
    accepted.update({
        "status": "accepted",
        "accepted_boot_id": current_boot,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "kiosk_lockdown_status": "applied",
        "kiosk_session_ready": True,
        "nautilus_ready": True,
        "account_separation_ready": True,
    })
    atomic_write_json(STATE_PATH, accepted, mode=0o600)
    return accepted


def main() -> int:
    try:
        result = verify_and_accept()
    except (OSError, ValueError, PostFinalRebootAcceptanceError) as exc:
        print(f"CLIENTFLOW_POST_FINAL_REBOOT_ACCEPTANCE_PENDING: {exc}", flush=True)
        return 1
    print(f"CLIENTFLOW_POST_FINAL_REBOOT_ACCEPTANCE_OK: {result.get('status')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
