"""GNOME Mutter ScreenCast -> PipeWire -> GStreamer HLS capture helper.

This helper is intentionally standalone and is executed with /usr/bin/python3
inside the active graphical user's GNOME/Wayland session. It has no backend
credential and does not use the XDG ScreenCast portal, so normal automated
livestream start/stop never requires a screen-selection dialog.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import gi

gi.require_version("Gio", "2.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gio, GLib, Gst

MUTTER_DEST = "org.gnome.Mutter.ScreenCast"
MUTTER_ROOT = "/org/gnome/Mutter/ScreenCast"
MUTTER_ROOT_IFACE = "org.gnome.Mutter.ScreenCast"
MUTTER_SESSION_IFACE = "org.gnome.Mutter.ScreenCast.Session"
MUTTER_STREAM_IFACE = "org.gnome.Mutter.ScreenCast.Stream"
DISPLAY_DEST = "org.gnome.Mutter.DisplayConfig"
DISPLAY_ROOT = "/org/gnome/Mutter/DisplayConfig"
DISPLAY_IFACE = "org.gnome.Mutter.DisplayConfig"

_STOP = False


def _handle_stop(_signum, _frame) -> None:
    global _STOP
    _STOP = True


def _require_elements() -> None:
    required = (
        "pipewiresrc",
        "queue",
        "videoconvert",
        "videorate",
        "x264enc",
        "h264parse",
        "mpegtsmux",
        "hlssink",
    )
    missing = [name for name in required if Gst.ElementFactory.find(name) is None]
    if missing:
        raise RuntimeError("Missing GStreamer elements: " + ", ".join(missing))


def _call(
    bus: Gio.DBusConnection,
    destination: str,
    path: str,
    interface: str,
    method: str,
    parameters: GLib.Variant | None = None,
    reply_signature: str | None = None,
    timeout_ms: int = 10_000,
):
    reply_type = GLib.VariantType.new(reply_signature) if reply_signature else None
    return bus.call_sync(
        destination,
        path,
        interface,
        method,
        parameters,
        reply_type,
        Gio.DBusCallFlags.NONE,
        timeout_ms,
        None,
    )


def _monitor_candidates() -> list[str]:
    """Return active connector candidates, preferring the current Mutter monitor."""
    candidates: list[str] = []
    forced = os.environ.get("CLIENTFLOW_MONITOR", "").strip()
    if forced:
        candidates.append(forced)

    try:
        out = subprocess.check_output(
            [
                "/usr/bin/gdbus",
                "call",
                "--session",
                "--dest",
                DISPLAY_DEST,
                "--object-path",
                DISPLAY_ROOT,
                "--method",
                f"{DISPLAY_IFACE}.GetCurrentState",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        # Connector names are stable Mutter identifiers such as HDMI-1, DP-1, eDP-1.
        for value in re.findall(r"'((?:DP|HDMI|eDP|DVI|VGA|Virtual)-\d+(?:-\d+)?)'", out):
            if value not in candidates:
                candidates.append(value)
    except Exception:
        pass

    return candidates or ["HDMI-1"]


class MutterScreenCast:
    def __init__(self) -> None:
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.session_path: str | None = None
        self.stream_path: str | None = None
        self.subscription_id: int = 0
        self.node_id: int | None = None
        self.loop: GLib.MainLoop | None = None

    def create_session(self) -> None:
        options = {"disable-animations": GLib.Variant("b", True)}
        result = _call(
            self.bus,
            MUTTER_DEST,
            MUTTER_ROOT,
            MUTTER_ROOT_IFACE,
            "CreateSession",
            GLib.Variant("(a{sv})", (options,)),
            "(o)",
        )
        self.session_path = str(result.unpack()[0])
        if not self.session_path.startswith("/"):
            raise RuntimeError("Mutter returned no ScreenCast session path")

    def record_monitor(self) -> str:
        if not self.session_path:
            raise RuntimeError("Mutter ScreenCast session is not created")
        options = {"cursor-mode": GLib.Variant("u", 1)}
        last_error: Exception | None = None
        for connector in _monitor_candidates():
            try:
                result = _call(
                    self.bus,
                    MUTTER_DEST,
                    self.session_path,
                    MUTTER_SESSION_IFACE,
                    "RecordMonitor",
                    GLib.Variant("(sa{sv})", (connector, options)),
                    "(o)",
                )
                self.stream_path = str(result.unpack()[0])
                if not self.stream_path.startswith("/"):
                    raise RuntimeError("Mutter returned no ScreenCast stream path")
                return connector
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                if "unknown monitor" in message or "ukendt monitor" in message:
                    continue
                raise
        raise RuntimeError(f"No valid Mutter monitor found: {last_error}")

    def _on_signal(self, _connection, _sender, _path, _interface, signal_name, parameters):
        if signal_name != "PipeWireStreamAdded":
            return
        try:
            values = parameters.unpack()
            for value in values:
                if isinstance(value, int):
                    self.node_id = int(value)
                    if self.loop is not None:
                        self.loop.quit()
                    return
        except Exception:
            return

    def start(self) -> int:
        if not self.session_path or not self.stream_path:
            raise RuntimeError("Mutter ScreenCast stream is not prepared")

        # Subscribe before Session.Start so the PipeWireStreamAdded signal cannot race us.
        self.subscription_id = self.bus.signal_subscribe(
            MUTTER_DEST,
            MUTTER_STREAM_IFACE,
            "PipeWireStreamAdded",
            self.stream_path,
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_signal,
        )
        _call(
            self.bus,
            MUTTER_DEST,
            self.session_path,
            MUTTER_SESSION_IFACE,
            "Start",
            None,
            None,
        )

        self.loop = GLib.MainLoop()
        timed_out = {"value": False}

        def timeout():
            timed_out["value"] = True
            if self.loop is not None:
                self.loop.quit()
            return GLib.SOURCE_REMOVE

        timer = GLib.timeout_add_seconds(10, timeout)
        try:
            if self.node_id is None:
                self.loop.run()
        finally:
            if timer:
                try:
                    GLib.source_remove(timer)
                except Exception:
                    pass
            self.loop = None

        if timed_out["value"] or self.node_id is None:
            raise RuntimeError("Mutter returned no PipeWire node within 10 seconds")
        return self.node_id

    def close(self) -> None:
        if self.subscription_id:
            try:
                self.bus.signal_unsubscribe(self.subscription_id)
            except Exception:
                pass
            self.subscription_id = 0
        if self.session_path:
            try:
                _call(
                    self.bus,
                    MUTTER_DEST,
                    self.session_path,
                    MUTTER_SESSION_IFACE,
                    "Stop",
                    None,
                    None,
                    timeout_ms=5_000,
                )
            except Exception:
                pass
            self.session_path = None


def _build_pipeline(
    node_id: int,
    output: Path,
    fps: int,
    bitrate_kbit: int,
    preset: str,
    segment_seconds: int,
    playlist_size: int,
) -> Gst.Pipeline:
    location = str(output / "segment-%09d.ts").replace('"', '\\"')
    playlist = str(output / "index.m3u8").replace('"', '\\"')
    key_interval = fps * segment_seconds
    max_files = playlist_size + 2
    keepalive_ms = max(1, round(1000 / fps))

    # No width/height cap is applied: Mutter's monitor stream stays at native
    # resolution. videorate establishes the approved 10 fps cadence while
    # pipewiresrc keepalive repeats the last frame on a static desktop.
    description = (
        f"pipewiresrc path={node_id} do-timestamp=true on-disconnect=error "
        f"keepalive-time={keepalive_ms} "
        "! queue max-size-buffers=8 leaky=downstream "
        "! videoconvert ! videorate "
        f"! video/x-raw,format=I420,framerate={fps}/1 "
        f"! x264enc tune=zerolatency speed-preset={preset} key-int-max={key_interval} "
        f"bframes=0 bitrate={bitrate_kbit} "
        "! h264parse config-interval=-1 "
        "! mpegtsmux "
        f"! hlssink target-duration={segment_seconds} playlist-length={playlist_size} "
        f"max-files={max_files} location=\"{location}\" playlist-location=\"{playlist}\""
    )
    pipeline = Gst.parse_launch(description)
    if not isinstance(pipeline, Gst.Pipeline):
        raise RuntimeError("GStreamer pipeline could not be created")
    return pipeline


def _run_pipeline(pipeline: Gst.Pipeline) -> None:
    bus = pipeline.get_bus()
    state_result = pipeline.set_state(Gst.State.PLAYING)
    if state_result == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("GStreamer could not enter PLAYING state")
    try:
        while not _STOP:
            message = bus.timed_pop_filtered(
                Gst.SECOND,
                Gst.MessageType.ERROR | Gst.MessageType.EOS,
            )
            if message is None:
                continue
            if message.type == Gst.MessageType.ERROR:
                error, debug = message.parse_error()
                raise RuntimeError(f"GStreamer error: {error.message}; debug={debug or ''}")
            if message.type == Gst.MessageType.EOS:
                if not _STOP:
                    raise RuntimeError("GStreamer stream ended unexpectedly")
                break
    finally:
        pipeline.set_state(Gst.State.NULL)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--bitrate-kbit", type=int, required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--segment-seconds", type=int, required=True)
    parser.add_argument("--playlist-size", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        raise RuntimeError("Output path must be absolute")
    if not 1 <= args.fps <= 30:
        raise RuntimeError("fps is outside allowed range")
    if not 1000 <= args.bitrate_kbit <= 50000:
        raise RuntimeError("bitrate_kbit is outside allowed range")
    if args.preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}:
        raise RuntimeError("Unsupported x264 preset")
    if not 1 <= args.segment_seconds <= 10:
        raise RuntimeError("segment_seconds is outside allowed range")
    if not 3 <= args.playlist_size <= 30:
        raise RuntimeError("playlist_size is outside allowed range")
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        raise RuntimeError("Active graphical session is not Wayland")

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    Gst.init(None)
    _require_elements()
    output.mkdir(parents=True, exist_ok=True)

    capture = MutterScreenCast()
    try:
        capture.create_session()
        monitor = capture.record_monitor()
        node_id = capture.start()
        print(
            f"clientflow_wayland_capture_ready backend=mutter node={node_id} "
            f"monitor={monitor} fps={args.fps} bitrate_kbit={args.bitrate_kbit}",
            flush=True,
        )
        pipeline = _build_pipeline(
            node_id,
            output,
            args.fps,
            args.bitrate_kbit,
            args.preset,
            args.segment_seconds,
            args.playlist_size,
        )
        _run_pipeline(pipeline)
        return 0
    finally:
        capture.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"clientflow_wayland_capture_failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
