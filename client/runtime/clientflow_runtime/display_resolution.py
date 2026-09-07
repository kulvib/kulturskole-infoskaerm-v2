"""GNOME/Mutter Wayland display detection and fixed-mode application for ClientFlow Display."""
from __future__ import annotations

from datetime import datetime, timezone
import re
import subprocess
import time
from typing import Any

DEST = "org.gnome.Mutter.DisplayConfig"
OBJ = "/org/gnome/Mutter/DisplayConfig"
ROTATION_MAP = {"normal": 0, "right": 1, "inverted": 2, "left": 3}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _run(args: list[str], *, environment: dict[str, str], timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
        env=environment,
    )


def _balanced_slice(text: str, start_idx: int, open_char: str = "[", close_char: str = "]") -> tuple[str, int]:
    index = text.find(open_char, start_idx)
    if index < 0:
        return "", start_idx
    depth = 0
    in_string = False
    escaped = False
    begin = index + 1
    for cursor in range(index, len(text)):
        char = text[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_string = False
            continue
        if char == "'":
            in_string = True
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return text[begin:cursor], cursor + 1
    return "", start_idx


_MONITOR_RE = re.compile(r"\(\('([^']+)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'\),\s*\[", re.S)
_MODE_RE = re.compile(
    r"\('([^']+)',\s*(\d+),\s*(\d+),\s*([0-9.]+),\s*([0-9.]+),\s*\[[^\]]*\],\s*\{(.*?)\}\)",
    re.S,
)


def _bool_prop(props: str, name: str) -> bool:
    return bool(re.search(rf"'{re.escape(name)}':\s*<true>", props))


def _iter_monitors(text: str):
    for match in _MONITOR_RE.finditer(text):
        connector, vendor, product, serial = match.groups()
        modes_text, modes_end = _balanced_slice(text, match.end() - 1)
        if not modes_text:
            continue
        props_text = ""
        props_start = text.find("{", modes_end)
        next_monitor = text.find("(('", modes_end + 1)
        if props_start >= 0 and (next_monitor < 0 or props_start < next_monitor):
            props_text, _ = _balanced_slice(text, props_start, "{", "}")
        yield connector, vendor, product, serial, modes_text, props_text


def _parse_state(text: str) -> dict[str, Any]:
    displays: list[dict[str, Any]] = []
    for connector, vendor, product, serial, modes_text, props_text in _iter_monitors(text):
        modes: list[dict[str, Any]] = []
        current_mode: dict[str, Any] | None = None
        preferred_mode: dict[str, Any] | None = None
        for match in _MODE_RE.finditer(modes_text):
            label, width, height, refresh, scale, mode_props = match.groups()
            try:
                refresh_value = round(float(refresh), 3)
                scale_value = float(scale)
            except ValueError:
                continue
            item = {
                "id": label,
                "width": int(width),
                "height": int(height),
                "refresh_rate": refresh_value,
                "rates": [refresh_value],
                "scale": scale_value,
                "current": _bool_prop(mode_props, "is-current"),
                "preferred": _bool_prop(mode_props, "is-preferred"),
            }
            modes.append(item)
            if item["current"]:
                current_mode = item
            if item["preferred"] and preferred_mode is None:
                preferred_mode = item
        selected = current_mode or preferred_mode or (modes[0] if modes else None)
        displays.append({
            "output": connector,
            "name": connector,
            "vendor": vendor,
            "product": product,
            "serial": serial,
            "connected": True,
            "primary": _bool_prop(props_text, "is-builtin") or len(displays) == 0,
            "width": selected.get("width") if selected else None,
            "height": selected.get("height") if selected else None,
            "refresh_rate": selected.get("refresh_rate") if selected else None,
            "current_width": current_mode.get("width") if current_mode else None,
            "current_height": current_mode.get("height") if current_mode else None,
            "current_refresh_rate": current_mode.get("refresh_rate") if current_mode else None,
            "preferred_width": preferred_mode.get("width") if preferred_mode else None,
            "preferred_height": preferred_mode.get("height") if preferred_mode else None,
            "preferred_refresh_rate": preferred_mode.get("refresh_rate") if preferred_mode else None,
            "modes": modes,
        })
    active = [item for item in displays if item.get("width") and item.get("height")]
    selected = active[0] if active else (displays[0] if displays else None)
    return {
        "output": selected.get("output") if selected else None,
        "width": selected.get("width") if selected else None,
        "height": selected.get("height") if selected else None,
        "refresh_rate": selected.get("refresh_rate") if selected else None,
        "outputs": displays,
        "connected_count": len(displays),
        "primary_output": selected.get("output") if selected else None,
    }


def detect(*, environment: dict[str, str]) -> dict[str, Any]:
    result = _run(
        ["/usr/bin/gdbus", "call", "--session", "--dest", DEST, "--object-path", OBJ, "--method", f"{DEST}.GetCurrentState"],
        environment=environment,
        timeout=6.0,
    )
    if result.returncode != 0:
        return {"ok": False, "output": None, "width": None, "height": None, "refresh_rate": None, "outputs": [], "detected_at": _utc_now_iso(), "error": (result.stderr or result.stdout or "GetCurrentState fejlede").strip()[:1000]}
    info = _parse_state(result.stdout or "")
    if not info.get("output"):
        return {"ok": False, **info, "detected_at": _utc_now_iso(), "error": "Ingen aktiv Wayland/GNOME-skærm fundet via Mutter DisplayConfig"}
    return {"ok": True, **info, "detected_at": _utc_now_iso(), "error": None}


def _desired_mode(state_text: str, *, width: int, height: int, refresh_rate: float | None, output: str | None) -> tuple[str, str, float, float]:
    chosen: tuple[float, str, str, float, float] | None = None
    available: list[str] = []
    for connector, _vendor, _product, _serial, modes_text, _props in _iter_monitors(state_text):
        if output and connector != output:
            continue
        for match in _MODE_RE.finditer(modes_text):
            label, raw_width, raw_height, raw_refresh, raw_scale, _mode_props = match.groups()
            available.append(f"{connector}:{label}")
            if int(raw_width) != width or int(raw_height) != height:
                continue
            actual_refresh = float(raw_refresh)
            score = 0.0 if refresh_rate is None else abs(actual_refresh - refresh_rate)
            if refresh_rate is not None and score > 0.20:
                continue
            candidate = (score, connector, label, float(raw_scale), actual_refresh)
            if chosen is None or candidate[0] < chosen[0]:
                chosen = candidate
    if chosen is None:
        description = f"Ingen Mutter-mode matcher {width}x{height}"
        if refresh_rate is not None:
            description += f"@{refresh_rate}"
        if output:
            description += f" på {output}"
        if available:
            description += "; tilgængelige modes: " + ", ".join(available[:40])
        raise RuntimeError(description)
    _, connector, mode_id, scale, matched_refresh = chosen
    return connector, mode_id, scale, matched_refresh


def apply(*, environment: dict[str, str], width: int, height: int, refresh_rate: float | None, rotation: str, output: str | None = None) -> dict[str, Any]:
    if width < 320 or height < 240 or width > 16384 or height > 16384:
        raise ValueError("Skærmopløsningen er uden for det understøttede interval")
    if refresh_rate is not None and not (10.0 <= refresh_rate <= 500.0):
        raise ValueError("Refresh rate er uden for det understøttede interval")
    rotation = str(rotation or "normal").strip().lower()
    if rotation not in ROTATION_MAP:
        raise ValueError("Ugyldig display rotation")
    state = _run(
        ["/usr/bin/gdbus", "call", "--session", "--dest", DEST, "--object-path", OBJ, "--method", f"{DEST}.GetCurrentState"],
        environment=environment,
        timeout=6.0,
    )
    if state.returncode != 0:
        raise RuntimeError((state.stderr or state.stdout or "GetCurrentState fejlede").strip()[:1000])
    serial_match = re.search(r"^\(uint32\s+(\d+),", (state.stdout or "").strip())
    if not serial_match:
        raise RuntimeError("Kunne ikke finde Mutter serial i GetCurrentState-output")
    serial = int(serial_match.group(1))
    connector, mode_id, scale, matched_refresh = _desired_mode(
        state.stdout or "", width=width, height=height, refresh_rate=refresh_rate, output=output
    )
    logical = "[(0, 0, %.6g, uint32 %d, true, [('%s', '%s', @a{sv} {})])]" % (
        scale, ROTATION_MAP[rotation], connector, mode_id
    )
    result = _run(
        ["/usr/bin/gdbus", "call", "--session", "--dest", DEST, "--object-path", OBJ, "--method", f"{DEST}.ApplyMonitorsConfig", str(serial), "1", logical, "@a{sv} {}"],
        environment=environment,
        timeout=8.0,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "ApplyMonitorsConfig fejlede").strip()[:1000])
    time.sleep(1.0)
    observed = detect(environment=environment)
    return {"ok": bool(observed.get("ok")), "matched_refresh_rate": matched_refresh, **observed}
