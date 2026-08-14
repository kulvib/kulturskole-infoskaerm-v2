# ClientFlow 1.2 — Livestream v2 release overlay

Status: physically validated on Ubuntu 26.04 / GNOME 50 / Wayland on 2026-08-14.

This directory is deliberately a **ClientFlow 1.2 Livestream release overlay**, not a complete ClientFlow installer. The fresh backend repository does not yet contain the full 1.2 client installer/runtime source tree.

## Validated runtime design

- Viewer-owned lifecycle from Control Room: first viewer auto-starts; heartbeat 10 s; lease 30 s; last viewer gets 30 s stop grace.
- GNOME Mutter ScreenCast D-Bus backend; no XDG portal chooser during normal start/stop.
- PipeWire -> GStreamer -> H.264 High/yuv420p -> 2 s HLS.
- Native monitor capture, validated at 3440x1440, 10 fps, 12000 kbit/s, preset veryfast.
- PipeWire `keepalive-time` prevents static desktops from stalling HLS/media watchdog.
- Uploader tolerates only the benign rolling-HLS race where a segment disappears between scan and open; other file errors remain hard failures.
- Producer sandbox uses CAP_KILL, CAP_SETGID and CAP_SETUID only for the validated root-watcher -> graphical-user capture-child transition.

## Ubuntu dependencies

`ubuntu-packages.txt` makes the Livestream media dependencies explicit. In particular `gstreamer1.0-pipewire` is explicit rather than relying on transitive installation.

Run on a fresh compatible client:

    sudo client-release/livestream-v2/scripts/install_dependencies.sh

## Overlay installation

The overlay targets the physically validated release path `clientflow-1.2.0-seq-1200`. It refuses to install unless the existing Livestream desired state is `stopped`.

    sudo client-release/livestream-v2/scripts/install_overlay.sh

The installer backs up replaced Livestream files under `/var/backups` and only stops/restarts Livestream producer/uploader services.

## Validation

    sudo client-release/livestream-v2/scripts/validate_livestream.sh

Physical acceptance already completed on the reference Ubuntu client:

- Start / Restart / Stop / Start
- reboot/autologin persistence
- native-image quality
- CPU/RAM/temperature soak under realistic browser load
- static-screen keepalive
- uploader rolling-segment race
- viewer leave/return within 30 s keeps same generation
- viewer absent >30 s stops stream
- next viewer starts a new generation without GNOME dialog

Terminal, Remote Desktop, Display and System are outside this overlay and were not modified.
