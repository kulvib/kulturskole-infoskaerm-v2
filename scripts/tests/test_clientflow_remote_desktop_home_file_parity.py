from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/runtime"))

from clientflow_runtime.remote_desktop_files import FileArea



def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_remote_desktop_agent_uses_canonical_kiosk_home_and_private_staging():
    source = _read("client/runtime/clientflow_runtime/remote_desktop_agent.py")
    assert 'CLIENTFLOW_RD_FILE_ROOT", "/home/clientflow-kiosk"' in source
    assert 'CLIENTFLOW_RD_STAGING_ROOT", "/var/lib/clientflow/remote-desktop/uploads"' in source
    assert "FileArea(FILE_ROOT, FILE_STAGING_ROOT)" in source


def test_remote_desktop_agent_systemd_confines_home_access():
    source = _read("client/systemd/clientflow-remote-desktop-agent.service")
    assert "User=clientflow-remote-desktop-agent" in source
    assert "Group=clientflow-remote-desktop-agent" in source
    assert "NoNewPrivileges=yes" in source
    assert "ProtectSystem=strict" in source
    assert "ProtectHome=read-only" in source
    assert "ReadWritePaths=/home/@CLIENTFLOW_KIOSK_USER@" in source
    assert "ReadWritePaths=/root" not in source
    assert "ReadWritePaths=/etc" not in source


def test_release_provisions_physical_acl_without_following_symlinks():
    source = _read("client/release/lib/clientflow_release/transaction.py")
    assert "def _prepare_remote_desktop_home_access" in source
    assert '["/usr/bin/setfacl", "-P", "-R", "-m", f"u:{agent}:rwX", str(home)]' in source
    assert '"-xdev", "-type", "d", "-exec"' in source
    assert 'f"d:u:{agent}:rwx"' in source
    assert "_prepare_remote_desktop_home_access(layout)" in source
    assert "_prepare_remote_desktop_home_access(layout, _definition_kiosk_user(layout, kiosk_user))" in source


def test_file_area_rejects_absolute_parent_and_symlink_escape(tmp_path: Path):
    root = tmp_path / "home"
    staging = tmp_path / "staging"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (root / "visible.txt").write_text("ok", encoding="utf-8")
    (root / ".hidden.txt").write_text("hidden", encoding="utf-8")
    (root / "escape").symlink_to(outside, target_is_directory=True)

    area = FileArea(root, staging)
    with pytest.raises(ValueError, match="Filstien er ugyldig"):
        area.list("/etc")
    with pytest.raises(ValueError, match="Filstien er ugyldig"):
        area.list("../outside")
    with pytest.raises(ValueError):
        area.list("escape")

    result = area.list("")
    names = {entry["name"] for entry in result["entries"]}
    assert "visible.txt" in names
    assert ".hidden.txt" in names
    assert "escape" not in names


def test_backend_presents_canonical_home_path_and_preserves_hidden_toggle():
    source = _read("backend/service1/routers/remote_desktop_v2.py")
    assert 'REMOTE_DESKTOP_HOME_PATH = "/home/clientflow-kiosk"' in source
    assert '"home_path": REMOTE_DESKTOP_HOME_PATH' in source
    assert 'f"{REMOTE_DESKTOP_HOME_PATH}/{path}" if path else REMOTE_DESKTOP_HOME_PATH' in source
    assert "show_hidden: bool = False" in source
    assert "if hidden and not show_hidden:" in source
