from __future__ import annotations

import getpass
import os
from pathlib import Path
import pwd
import grp
import re
import subprocess

KIOSK_USER = "clientflow-kiosk"
KIOSK_DISPLAY_NAME = "ClientFlow kiosk user"
ADMIN_USER = "cfadmin"
ADMIN_DISPLAY_NAME = "ClientFlow local admin"

_PRIVILEGED_KIOSK_GROUPS = ("sudo", "adm", "admin", "wheel", "lpadmin", "lxd")


class AccountProvisioningError(RuntimeError):
    pass


def _run(command: list[str], *, input_text: str | None = None) -> None:
    result = subprocess.run(
        command,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if result.returncode != 0:
        raise AccountProvisioningError(
            f"Kommando fejlede ({result.returncode}): {' '.join(command)}\n{(result.stdout or '')[-2000:]}"
        )


def _interactive_password() -> str:
    first = getpass.getpass("Nyt password til cfadmin: ")
    second = getpass.getpass("Gentag password til cfadmin: ")
    if first != second:
        raise AccountProvisioningError("De to cfadmin-passwords er ikke ens")
    if len(first) < 8:
        raise AccountProvisioningError("cfadmin-password skal være mindst 8 tegn")
    if "\n" in first or "\r" in first or ":" in first:
        raise AccountProvisioningError("cfadmin-password indeholder ugyldige tegn")
    return first


def _ensure_group(name: str) -> None:
    try:
        grp.getgrnam(name)
    except KeyError:
        _run(["/usr/sbin/groupadd", "--force", name])


def _ensure_user(name: str, *, comment: str) -> None:
    try:
        pwd.getpwnam(name)
    except KeyError:
        _run([
            "/usr/sbin/useradd",
            "--create-home",
            "--user-group",
            "--shell",
            "/bin/bash",
            "--comment",
            comment,
            name,
        ])
    else:
        _run(["/usr/sbin/usermod", "--shell", "/bin/bash", "--comment", comment, name])


def _remove_group_membership(user: str, group: str) -> None:
    try:
        members = grp.getgrnam(group).gr_mem
    except KeyError:
        return
    if user in members:
        result = subprocess.run(
            ["/usr/bin/gpasswd", "--delete", user, group],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode not in {0, 3}:
            raise AccountProvisioningError(f"Kunne ikke fjerne {user} fra gruppen {group}")


def _account_groups(user: str) -> set[str]:
    account = pwd.getpwnam(user)
    names: set[str] = set()
    for gid in os.getgrouplist(user, account.pw_gid):
        try:
            names.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            continue
    return names


def _validate_human_accounts() -> None:
    kiosk = pwd.getpwnam(KIOSK_USER)
    admin = pwd.getpwnam(ADMIN_USER)
    if kiosk.pw_uid < 1000 or kiosk.pw_uid == 0 or admin.pw_uid < 1000 or admin.pw_uid == 0:
        raise AccountProvisioningError("Kiosk/admin skal være normale lokale brugere")
    if kiosk.pw_dir != f"/home/{KIOSK_USER}" or admin.pw_dir != f"/home/{ADMIN_USER}":
        raise AccountProvisioningError("Kiosk/admin home matcher ikke canonical account contract")
    if kiosk.pw_shell != "/bin/bash" or admin.pw_shell != "/bin/bash":
        raise AccountProvisioningError("Kiosk/admin shell matcher ikke canonical account contract")
    kiosk_groups = _account_groups(KIOSK_USER)
    if kiosk_groups.intersection(_PRIVILEGED_KIOSK_GROUPS):
        raise AccountProvisioningError("Kiosk-brugeren har privilegerede lokale grupper")
    if "sudo" not in _account_groups(ADMIN_USER):
        raise AccountProvisioningError("cfadmin mangler sudo-gruppen")



def detect_bootstrap_user() -> str | None:
    """Return the pre-ClientFlow interactive Ubuntu user when invoked through sudo.

    Fresh-install state records only the username, never credentials.  Direct
    root execution has no bootstrap user.  Canonical ClientFlow human accounts
    are always protected from this classification.
    """
    candidate = str(os.environ.get("SUDO_USER") or "").strip()
    if not candidate or candidate in {"root", KIOSK_USER, ADMIN_USER}:
        return None
    try:
        account = pwd.getpwnam(candidate)
    except KeyError:
        return None
    if account.pw_uid < 1000 or account.pw_uid >= 65000:
        return None
    return candidate


def cleanup_bootstrap_user(name: str | None) -> None:
    """Remove the exact recorded Ubuntu bootstrap user after healthy activation.

    This intentionally does not enumerate or delete arbitrary local users.  The
    fresh transaction records one exact pre-ClientFlow user and only that user
    may be removed by this lifecycle hook.
    """
    candidate = str(name or "").strip()
    if not candidate:
        return
    if candidate in {"root", KIOSK_USER, ADMIN_USER}:
        raise AccountProvisioningError("Bootstrap-user matcher en beskyttet ClientFlow-bruger")
    try:
        account = pwd.getpwnam(candidate)
    except KeyError:
        return
    if account.pw_uid < 1000 or account.pw_uid >= 65000:
        raise AccountProvisioningError("Bootstrap-user er ikke en normal lokal Ubuntu-bruger")

    subprocess.run(["/usr/bin/loginctl", "terminate-user", candidate], check=False)
    subprocess.run(["/usr/bin/pkill", "-TERM", "-u", candidate], check=False)
    result = subprocess.run(
        ["/usr/sbin/userdel", "--remove", candidate],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AccountProvisioningError(
            f"Kunne ikke fjerne bootstrap-user {candidate}: {(result.stdout or '')[-1000:]}"
        )
    try:
        pwd.getpwnam(candidate)
    except KeyError:
        return
    raise AccountProvisioningError(f"Bootstrap-user {candidate} findes stadig efter userdel")

def provision_human_accounts(*, prompt_admin_password: bool = True, admin_password: str | None = None) -> dict[str, str]:
    if os.geteuid() != 0:
        raise AccountProvisioningError("Human-account provisioning kræver root")

    _ensure_user(KIOSK_USER, comment=KIOSK_DISPLAY_NAME)
    _ensure_user(ADMIN_USER, comment=ADMIN_DISPLAY_NAME)

    for group in _PRIVILEGED_KIOSK_GROUPS:
        _remove_group_membership(KIOSK_USER, group)

    # Kiosk-login is intentionally passwordless because GDM owns automatic
    # session entry; privilege elevation remains blocked by groups/polkit.
    _run(["/usr/bin/passwd", "--delete", KIOSK_USER])
    _run(["/usr/sbin/usermod", "--unlock", KIOSK_USER])

    _ensure_group("sudo")
    _run(["/usr/sbin/usermod", "--append", "--groups", "sudo", ADMIN_USER])

    password = admin_password
    if password is None and prompt_admin_password:
        password = _interactive_password()
    if password:
        if not re.fullmatch(r"[^:\r\n]{8,}", password):
            raise AccountProvisioningError("cfadmin-password opfylder ikke minimumskravet")
        _run(["/usr/sbin/chpasswd"], input_text=f"{ADMIN_USER}:{password}\n")

    _validate_human_accounts()
    return {"kiosk_user": KIOSK_USER, "admin_user": ADMIN_USER}
