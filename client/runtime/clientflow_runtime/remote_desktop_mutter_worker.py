"""Remote-Desktop-owned GNOME Mutter -> PipeWire -> JPEG worker.

Executed with Ubuntu's /usr/bin/python3 so PyGObject/GStreamer can be used.
The worker is deliberately network-free and communicates only over stdin/stdout
with the local Remote Desktop capture broker.
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.util
import json
import signal
import sys
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import Gio, GLib, Gst, GstApp

MUTTER_DEST = "org.gnome.Mutter.ScreenCast"
MUTTER_ROOT = "/org/gnome/Mutter/ScreenCast"
MUTTER_ROOT_IFACE = "org.gnome.Mutter.ScreenCast"
MUTTER_SESSION_IFACE = "org.gnome.Mutter.ScreenCast.Session"
MUTTER_STREAM_IFACE = "org.gnome.Mutter.ScreenCast.Stream"
DISPLAY_DEST = "org.gnome.Mutter.DisplayConfig"
DISPLAY_ROOT = "/org/gnome/Mutter/DisplayConfig"
DISPLAY_IFACE = "org.gnome.Mutter.DisplayConfig"
REMOTE_DESKTOP_DEST = "org.gnome.Mutter.RemoteDesktop"
REMOTE_DESKTOP_ROOT = "/org/gnome/Mutter/RemoteDesktop"
REMOTE_DESKTOP_ROOT_IFACE = "org.gnome.Mutter.RemoteDesktop"
REMOTE_DESKTOP_SESSION_IFACE = "org.gnome.Mutter.RemoteDesktop.Session"
MAX_FRAME_BYTES = 8 * 1024 * 1024

_STOP = False


def _stop(_signum, _frame) -> None:
    global _STOP
    _STOP = True


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


def _require_elements() -> None:
    required = ("pipewiresrc", "queue", "videoconvert", "videoscale", "jpegenc", "appsink")
    missing = [name for name in required if Gst.ElementFactory.find(name) is None]
    if missing:
        raise RuntimeError("Mangler GStreamer-elementer: " + ", ".join(missing))


class MutterScreenCast:
    def __init__(self) -> None:
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.session_path: str | None = None
        self.stream_path: str | None = None
        self.subscription_id = 0
        self.node_id: int | None = None
        self.loop: GLib.MainLoop | None = None
        self.monitor: str | None = None

    def monitor_candidates(self, preferred: str | None) -> list[str]:
        candidates: list[str] = []
        if preferred:
            candidates.append(preferred)
        result = _call(
            self.bus,
            DISPLAY_DEST,
            DISPLAY_ROOT,
            DISPLAY_IFACE,
            "GetCurrentState",
        ).unpack()
        for monitor in result[1]:
            try:
                connector = str(monitor[0][0])
            except Exception:
                continue
            if connector and connector not in candidates:
                candidates.append(connector)
        if not candidates:
            raise RuntimeError("Mutter returnerede ingen aktive monitorer")
        return candidates

    def start(self, preferred_monitor: str | None) -> tuple[int, str]:
        self.close()
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
            raise RuntimeError("Mutter returnerede ingen ScreenCast-session")

        last_error: Exception | None = None
        for connector in self.monitor_candidates(preferred_monitor):
            try:
                result = _call(
                    self.bus,
                    MUTTER_DEST,
                    self.session_path,
                    MUTTER_SESSION_IFACE,
                    "RecordMonitor",
                    GLib.Variant(
                        "(sa{sv})",
                        (connector, {"cursor-mode": GLib.Variant("u", 1)}),
                    ),
                    "(o)",
                )
                self.stream_path = str(result.unpack()[0])
                self.monitor = connector
                break
            except Exception as exc:
                last_error = exc
        if not self.stream_path or not self.monitor:
            raise RuntimeError(f"Ingen Mutter-monitor kunne optages: {last_error}")

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
            try:
                GLib.source_remove(timer)
            except Exception:
                pass
            self.loop = None

        if timed_out["value"] or self.node_id is None:
            raise RuntimeError("Mutter returnerede ingen PipeWire-node")
        return self.node_id, self.monitor

    def _on_signal(self, _connection, _sender, _path, _interface, signal_name, parameters) -> None:
        if signal_name != "PipeWireStreamAdded":
            return
        for value in parameters.unpack():
            if isinstance(value, int):
                self.node_id = int(value)
                if self.loop is not None:
                    self.loop.quit()
                return

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
                    timeout_ms=5_000,
                )
            except Exception:
                pass
        self.session_path = None
        self.stream_path = None
        self.node_id = None
        self.monitor = None


class MutterKeyboard:
    """Unprivileged Unicode text injection through Mutter RemoteDesktop."""

    def __init__(self) -> None:
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        library = ctypes.util.find_library("xkbcommon")
        if not library:
            raise RuntimeError("libxkbcommon blev ikke fundet")
        self.xkb = ctypes.CDLL(library)
        self.xkb.xkb_utf32_to_keysym.argtypes = [ctypes.c_uint32]
        self.xkb.xkb_utf32_to_keysym.restype = ctypes.c_uint32
        self.session_path: str | None = None

    def _ensure_session(self) -> str:
        if self.session_path:
            return self.session_path
        result = _call(
            self.bus, REMOTE_DESKTOP_DEST, REMOTE_DESKTOP_ROOT,
            REMOTE_DESKTOP_ROOT_IFACE, "CreateSession", reply_signature="(o)",
        )
        session_path = str(result.unpack()[0])
        _call(
            self.bus, REMOTE_DESKTOP_DEST, session_path,
            REMOTE_DESKTOP_SESSION_IFACE, "Start",
        )
        self.session_path = session_path
        return session_path

    def _keysym(self, character: str) -> int:
        if character in {"\n", "\r"}:
            return 0xFF0D
        if character == "\t":
            return 0xFF09
        if ord(character) < 0x20 or ord(character) == 0x7F:
            raise ValueError(f"Kontroltegnet kan ikke indtastes sikkert: {character!r}")
        keysym = int(self.xkb.xkb_utf32_to_keysym(ord(character)))
        if keysym == 0:
            raise ValueError(f"Unicode-tegnet kan ikke oversættes: {character!r}")
        return keysym

    def _notify(self, session_path: str, keysym: int, pressed: bool) -> None:
        _call(
            self.bus, REMOTE_DESKTOP_DEST, session_path,
            REMOTE_DESKTOP_SESSION_IFACE, "NotifyKeyboardKeysym",
            GLib.Variant("(ub)", (keysym, pressed)),
        )

    def type_text(self, text: str) -> None:
        if len(text) > 1000:
            raise ValueError("Tekstinput er for langt")
        if not text:
            return
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                session_path = self._ensure_session()
                for character in text:
                    keysym = self._keysym(character)
                    self._notify(session_path, keysym, True)
                    self._notify(session_path, keysym, False)
                return
            except Exception as exc:
                last_error = exc
                self.close()
                if attempt == 0:
                    continue
                break
        raise RuntimeError(f"Mutter Unicode-input fejlede: {last_error}")

    def close(self) -> None:
        if not self.session_path:
            return
        try:
            _call(
                self.bus, REMOTE_DESKTOP_DEST, self.session_path,
                REMOTE_DESKTOP_SESSION_IFACE, "Stop", timeout_ms=5_000,
            )
        except Exception:
            pass
        self.session_path = None


class FramePipeline:
    def __init__(self) -> None:
        self.pipeline: Gst.Pipeline | None = None
        self.sink: GstApp.AppSink | None = None
        self.spec: tuple[int, int, int, int, bool] | None = None
        self.last_frame: bytes | None = None
        self.last_geometry: tuple[int, int] | None = None

    def close(self) -> None:
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.sink = None
        self.spec = None
        self.last_frame = None
        self.last_geometry = None

    def ensure(self, node_id: int, width: int, height: int, quality: int, native: bool = False) -> None:
        spec = (node_id, width, height, quality, bool(native))
        if self.pipeline is not None and self.spec == spec:
            return
        self.close()
        if native:
            description = (
                f"pipewiresrc path={node_id} do-timestamp=true on-disconnect=error keepalive-time=100 "
                "! queue max-size-buffers=2 leaky=downstream "
                "! videoconvert "
                f"! jpegenc quality={quality} "
                "! appsink name=frame_sink max-buffers=1 drop=true sync=false"
            )
        else:
            description = (
                f"pipewiresrc path={node_id} do-timestamp=true on-disconnect=error keepalive-time=100 "
                "! queue max-size-buffers=2 leaky=downstream "
                "! videoconvert ! videoscale "
                f"! video/x-raw,width={width},height={height},pixel-aspect-ratio=1/1 "
                f"! jpegenc quality={quality} "
                "! appsink name=frame_sink max-buffers=1 drop=true sync=false"
            )
        pipeline = Gst.parse_launch(description)
        if not isinstance(pipeline, Gst.Pipeline):
            raise RuntimeError("GStreamer pipeline kunne ikke oprettes")
        sink = pipeline.get_by_name("frame_sink")
        if not isinstance(sink, GstApp.AppSink):
            pipeline.set_state(Gst.State.NULL)
            raise RuntimeError("GStreamer appsink mangler")
        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            pipeline.set_state(Gst.State.NULL)
            raise RuntimeError("GStreamer kunne ikke starte")
        self.pipeline = pipeline
        self.sink = sink
        self.spec = spec

    def capture(self) -> tuple[bytes, int, int]:
        if self.pipeline is None or self.sink is None:
            raise RuntimeError("GStreamer pipeline er ikke startet")
        bus = self.pipeline.get_bus()
        message = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if message is not None:
            if message.type == Gst.MessageType.ERROR:
                error, debug = message.parse_error()
                raise RuntimeError(f"GStreamer-fejl: {error.message}; debug={debug or ''}")
            raise RuntimeError("GStreamer-stream stoppede")

        sample = self.sink.try_pull_sample(2 * Gst.SECOND)
        if sample is None:
            if self.last_frame is not None and self.last_geometry is not None:
                return self.last_frame, self.last_geometry[0], self.last_geometry[1]
            raise RuntimeError("GStreamer returnerede ingen frame")
        caps = sample.get_caps()
        if caps is None or caps.get_size() < 1:
            raise RuntimeError("GStreamer-frame mangler geometri")
        structure = caps.get_structure(0)
        ok_width, actual_width = structure.get_int("width")
        ok_height, actual_height = structure.get_int("height")
        if not ok_width or not ok_height or actual_width <= 0 or actual_height <= 0:
            raise RuntimeError("GStreamer-frame har ugyldig geometri")
        buffer = sample.get_buffer()
        if buffer is None:
            raise RuntimeError("GStreamer returnerede ingen buffer")
        ok, info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError("GStreamer-frame kunne ikke læses")
        try:
            frame = bytes(info.data)
        finally:
            buffer.unmap(info)
        if not frame or len(frame) > MAX_FRAME_BYTES:
            raise RuntimeError("Mutter/PipeWire returnerede en tom eller for stor frame")
        self.last_frame = frame
        self.last_geometry = (int(actual_width), int(actual_height))
        return frame, int(actual_width), int(actual_height)


class Worker:
    def __init__(self) -> None:
        self.cast = MutterScreenCast()
        self.keyboard = MutterKeyboard()
        self.pipeline = FramePipeline()
        self.node_id: int | None = None
        self.monitor: str | None = None
        self.requested_monitor: str | None = None

    def stop_capture(self) -> None:
        self.pipeline.close()
        self.cast.close()
        self.node_id = None
        self.monitor = None
        self.requested_monitor = None

    def close(self) -> None:
        self.stop_capture()
        self.keyboard.close()

    def _start_stream(self, requested_monitor: str | None) -> None:
        self.pipeline.close()
        self.node_id, self.monitor = self.cast.start(requested_monitor)
        self.requested_monitor = requested_monitor

    def capture(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("action") != "capture":
            raise ValueError("Worker accepterer kun capture")
        native = bool(request.get("native", False))
        width = int(request.get("width", 1280))
        height = int(request.get("height", 720))
        quality = int(request.get("quality", 85))
        if (not native and (not 320 <= width <= 7680 or not 200 <= height <= 4320)) or not 20 <= quality <= 95:
            raise ValueError("Capture-dimensioner eller kvalitet er ugyldige")
        monitor_raw = request.get("monitor")
        requested_monitor = str(monitor_raw).strip() if monitor_raw else None

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                if self.node_id is None or requested_monitor != self.requested_monitor:
                    self._start_stream(requested_monitor)
                assert self.node_id is not None
                self.pipeline.ensure(self.node_id, width, height, quality, native=native)
                frame, actual_width, actual_height = self.pipeline.capture()
                return {
                    "ok": True,
                    "encoding": "base64",
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(frame).decode("ascii"),
                    "monitor": self.monitor,
                    "width": actual_width,
                    "height": actual_height,
                    "screen_width": actual_width,
                    "screen_height": actual_height,
                    "native": native,
                }
            except RuntimeError as exc:
                last_error = exc
                self.close()
                if attempt == 0:
                    continue
                break
        raise RuntimeError(f"Mutter/PipeWire capture kunne ikke genetableres: {last_error}")


    def text(self, request: dict[str, Any]) -> dict[str, Any]:
        text = str(request.get("text") or "")
        if len(text) > 1000:
            raise ValueError("Tekstinput er for langt")
        self.keyboard.type_text(text)
        return {"ok": True, "action": "text", "characters": len(text)}

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = str(request.get("action") or "")
        if action == "capture":
            return self.capture(request)
        if action == "text":
            return self.text(request)
        if action == "stop_capture":
            self.stop_capture()
            return {"ok": True, "action": action}
        raise ValueError("Worker accepterer kun capture, text og stop_capture")


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    Gst.init(None)
    _require_elements()
    worker = Worker()
    try:
        for raw in sys.stdin:
            if _STOP:
                break
            if len(raw) > 64 * 1024:
                _write({"ok": False, "error": "Worker-request er for stor"})
                continue
            try:
                request = json.loads(raw)
                if not isinstance(request, dict):
                    raise ValueError("Worker-request skal være et JSON-objekt")
                _write(worker.handle(request))
            except Exception as exc:
                _write({"ok": False, "error": str(exc)[:1000]})
        return 0
    finally:
        worker.close()


if __name__ == "__main__":
    raise SystemExit(main())
