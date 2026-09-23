from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[2]
USB = ROOT / "client/bootstrap/usb"
LAUNCHER = USB / "Start ClientFlow.EXE"
LAUNCHER_SOURCE = USB / "start_clientflow_launcher.S"
FLOW_LOGO = USB / "planiq-flow-logo.png"
SHORT_README = USB / "00_START_HER_KORT.txt"
LONG_README = USB / "README_START_HER.txt"
USB_BUILDER = ROOT / "scripts/build_clientflow_usb_installer.py"

# Original byte-for-byte Flow asset:
# flow-planiq-main/frontend/public/brand/planiq-flow/planiq-flow-logo.png
ORIGINAL_FLOW_LOGO_SHA256 = "39a257f857aba6acce310137fceb25ca852635adae3bf31875096358f4f803f9"


def _elf_program_header_types(raw: bytes) -> list[tuple[int, int]]:
    assert raw[:4] == b"\x7fELF"
    assert raw[4] == 2, "launcher must be ELF64"
    assert raw[5] == 1, "launcher must be little-endian"
    phoff = struct.unpack_from("<Q", raw, 32)[0]
    phentsize = struct.unpack_from("<H", raw, 54)[0]
    phnum = struct.unpack_from("<H", raw, 56)[0]
    result: list[tuple[int, int]] = []
    for index in range(phnum):
        offset = phoff + index * phentsize
        p_type = struct.unpack_from("<I", raw, offset)[0]
        p_flags = struct.unpack_from("<I", raw, offset + 4)[0]
        result.append((p_type, p_flags))
    return result


def test_usb_click_launcher_is_static_linux_amd64_elf_without_executable_stack() -> None:
    raw = LAUNCHER.read_bytes()
    assert raw[:4] == b"\x7fELF"
    assert struct.unpack_from("<H", raw, 16)[0] == 2  # ET_EXEC
    assert struct.unpack_from("<H", raw, 18)[0] == 62  # EM_X86_64
    headers = _elf_program_header_types(raw)
    assert all(p_type != 3 for p_type, _flags in headers), "PT_INTERP must be absent"
    gnu_stack = [flags for p_type, flags in headers if p_type == 0x6474E551]
    assert gnu_stack and all((flags & 0x1) == 0 for flags in gnu_stack)


def test_usb_click_launcher_is_only_a_terminal_shim_to_canonical_entrypoint() -> None:
    raw = LAUNCHER.read_bytes()
    source = LAUNCHER_SOURCE.read_text(encoding="utf-8")
    assert b"./01_START_CLIENTFLOW_USB.sh\x00" in raw
    assert b"/usr/bin/ptyxis\x00" in raw
    assert b"/usr/bin/bash\x00" in raw
    assert b"sudo" not in raw
    assert b"curl" not in raw
    assert b"wget" not in raw
    assert b"github.com" not in raw.lower()
    assert b"onrender.com" not in raw.lower()
    assert "__NR_execve" in source
    assert "01_START_CLIENTFLOW_USB.sh" in source
    assert "bootstrap" in source.lower()
    assert "checksum" in source.lower()
    assert "release-selection" in source.lower()


def test_usb_flow_branding_is_exact_original_flow_asset() -> None:
    raw = FLOW_LOGO.read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_FLOW_LOGO_SHA256


def test_usb_builder_packages_launcher_and_branding_under_top_level_integrity(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("clientflow_usb_click_builder", USB_BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    output = tmp_path / "usb.zip"
    module.build(output)
    with zipfile.ZipFile(output) as archive:
        launcher = archive.read("Start ClientFlow.EXE")
        logo = archive.read("PlanIQ Flow.png")
        top_manifest = archive.read("USB_SHA256SUMS.txt").decode("utf-8")
        payload_manifest = archive.read("PAYLOAD_SHA256SUMS.txt").decode("utf-8")
        launcher_mode = (archive.getinfo("Start ClientFlow.EXE").external_attr >> 16) & 0o777
        logo_mode = (archive.getinfo("PlanIQ Flow.png").external_attr >> 16) & 0o777

    assert launcher == LAUNCHER.read_bytes()
    assert logo == FLOW_LOGO.read_bytes()
    assert launcher_mode == 0o555
    assert logo_mode == 0o444
    assert f"{hashlib.sha256(launcher).hexdigest()}  Start ClientFlow.EXE" in top_manifest
    assert f"{hashlib.sha256(logo).hexdigest()}  PlanIQ Flow.png" in top_manifest
    assert "Start ClientFlow.EXE" not in payload_manifest
    assert "PlanIQ Flow.png" not in payload_manifest


def test_usb_readmes_make_clickable_start_primary_and_keep_terminal_recovery() -> None:
    short = SHORT_README.read_text(encoding="utf-8")
    long = LONG_README.read_text(encoding="utf-8")
    for text in (short, long):
        assert "Start ClientFlow.EXE" in text
        assert "bash 01_START_CLIENTFLOW_USB.sh" in text
    assert long.index('Dobbeltklik på "Start ClientFlow.EXE"') < long.index(
        "bash 01_START_CLIENTFLOW_USB.sh"
    )
    assert "originale, uændrede PlanIQ Flow-logo" in long
