# Livestream v2 — frozen physical validation

This repo overlay combines:

1. the deployed viewer-owned backend/Control Room lifecycle, and
2. the physically validated ClientFlow 1.2 GNOME Mutter/PipeWire client overlay.

The client overlay is intentionally stored under `client-release/livestream-v2/` because the fresh repo does not yet contain the complete 1.2 client installer/runtime source tree.

`render.yaml` is intentionally not included in this patch.

## Lifecycle

- first viewer: auto Start
- heartbeat: 10 seconds
- viewer lease: 30 seconds
- last viewer: 30-second Stop grace
- return during grace: same generation continues
- no viewer after grace: Stop
- next viewer: new generation
- media watchdog self-heal only while at least one viewer is active

## Client capture

- GNOME Mutter ScreenCast -> PipeWire -> GStreamer
- no portal chooser/restore-token dependency in normal runtime
- native capture at 10 fps / 12000 kbit/s / 2-second HLS
- static frame keepalive enabled

## Scope

Livestream only. Terminal, Remote Desktop, Display and System are untouched.
