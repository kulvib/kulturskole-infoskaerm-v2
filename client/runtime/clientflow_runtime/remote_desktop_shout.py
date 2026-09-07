"""Unprivileged, RD-owned fullscreen shout overlay for GNOME/Wayland."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys


def _wayland_display() -> str:
    configured = str(os.environ.get("WAYLAND_DISPLAY") or "").strip()
    if configured:
        return configured
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or "")
    if not runtime.is_dir():
        raise RuntimeError("XDG_RUNTIME_DIR mangler for Remote Desktop shout")
    for candidate in sorted(runtime.glob("wayland-*")):
        try:
            if stat.S_ISSOCK(candidate.stat().st_mode):
                return candidate.name
        except OSError:
            continue
    raise RuntimeError("Wayland-socket blev ikke fundet for Remote Desktop shout")


def main() -> int:
    if len(sys.argv) != 2:
        raise RuntimeError("Remote Desktop shout kræver én JSON-payload")
    payload = json.loads(sys.argv[1])
    if not isinstance(payload, dict):
        raise RuntimeError("Remote Desktop shout-payload er ugyldig")
    text = str(payload.get("text") or "").strip()
    if not text or len(text) > 120:
        raise ValueError("Shout-beskeden skal være 1-120 tegn")
    duration = max(3, min(30, int(payload.get("duration") or 8)))

    os.environ.setdefault("GDK_BACKEND", "wayland")
    os.environ["WAYLAND_DISPLAY"] = _wayland_display()

    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Pango", "1.0")
    from gi.repository import Gdk, Gio, GLib, Gtk, Pango

    app = Gtk.Application(
        application_id="dk.clientflow.RemoteDesktopShout",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def activate(application: Gtk.Application) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"window { background: #000000; } label { color: #ffffff; font-weight: 800; font-size: 72px; padding: 72px; }"
        )
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("Wayland-display kunne ikke åbnes for Remote Desktop shout")
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        window = Gtk.ApplicationWindow(application=application)
        window.set_title("ClientFlow Shout")
        window.set_decorated(False)
        label = Gtk.Label(label=text.upper())
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_justify(Gtk.Justification.CENTER)
        label.set_xalign(0.5)
        label.set_yalign(0.5)
        window.set_child(label)
        window.fullscreen()
        window.present()

        def close() -> bool:
            window.close()
            application.quit()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add_seconds(duration, close)

    app.connect("activate", activate)
    return int(app.run([]))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Remote Desktop shout fejlede: {exc}", file=sys.stderr, flush=True)
        raise
