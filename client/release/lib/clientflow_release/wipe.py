from __future__ import annotations

from pathlib import Path
import pwd
import grp
import shutil
import subprocess

from .transaction import Layout, _remove_definitions

USERS = (
    "clientflow",
    "clientflow-status",
    "clientflow-display-agent",
    "clientflow-display",
    "clientflow-livestream-agent",
    "clientflow-livestream-runtime",
    "clientflow-livestream-uploader",
    "clientflow-remote-desktop-agent",
    "clientflow-terminal-agent",
    "clientflow-terminal-session",
    "clientflow-system-agent",
    "clientflow-updater",
)
GROUPS = (
    "clientflow-display-control",
    "clientflow-livestream-control",
    *USERS,
)


def wipe(*, reason: str, confirm: str, layout: Layout = Layout()) -> None:
    if confirm != "DESTROY-CLIENTFLOW-STATE":
        raise RuntimeError("Wipe kræver den eksakte bekræftelse DESTROY-CLIENTFLOW-STATE")
    if len(reason.strip()) < 8:
        raise RuntimeError("Wipe kræver en konkret begrundelse")
    if layout.root == Path("/"):
        subprocess.run(["/usr/bin/systemctl", "disable", "--now", "clientflow-updater.timer"], check=False)
        subprocess.run(["/usr/bin/systemctl", "stop", "clientflow-updater.service"], check=False)
        subprocess.run(["/usr/bin/systemctl", "disable", "--now", "clientflow.target"], check=False)
    _remove_definitions(layout)
    sudoers_root = layout.path("/etc/sudoers.d")
    if sudoers_root.is_dir() and not sudoers_root.is_symlink():
        for path in sorted(sudoers_root.glob("clientflow*")):
            metadata = path.lstat()
            if metadata.st_mode & 0o022 or not path.is_file() or path.is_symlink():
                raise RuntimeError(f"Wipe afviste usikker sudoers-fil: {path}")
            path.unlink()
    for absolute in (
        "/opt/clientflow",
        "/etc/clientflow",
        "/var/lib/clientflow",
        "/run/clientflow",
        "/usr/lib/clientflow",
    ):
        path = layout.path(absolute)
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    if layout.root == Path("/"):
        subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=False)
        for user in USERS:
            try:
                pwd.getpwnam(user)
            except KeyError:
                continue
            subprocess.run(["/usr/sbin/userdel", user], check=False)
        for group in GROUPS:
            try:
                grp.getgrnam(group)
            except KeyError:
                continue
            subprocess.run(["/usr/sbin/groupdel", group], check=False)
