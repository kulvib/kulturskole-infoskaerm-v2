from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCAL_GUI = ROOT / "client/libexec/local-gui"


def test_local_gui_requires_gtk4_and_gdk4_before_gi_repository_import() -> None:
    source = LOCAL_GUI.read_text(encoding="utf-8")
    gtk = 'gi.require_version("Gtk", "4.0")'
    gdk = 'gi.require_version("Gdk", "4.0")'
    repo_import = 'from gi.repository import Gdk, GLib, Gtk, Pango'

    assert gtk in source
    assert gdk in source
    assert repo_import in source
    assert source.index(gtk) < source.index(repo_import)
    assert source.index(gdk) < source.index(repo_import)
