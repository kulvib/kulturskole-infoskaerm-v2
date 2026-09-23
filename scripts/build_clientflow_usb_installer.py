#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "client/bootstrap"
USB = BOOTSTRAP / "usb"
PAYLOAD_SOURCES = {
    "clientflow-factory-prepare": (BOOTSTRAP / "clientflow-factory-prepare", 0o555),
    "clientflow-fresh-install": (BOOTSTRAP / "clientflow-fresh-install", 0o555),
    "clientflow_bootstrap_common.py": (BOOTSTRAP / "clientflow_bootstrap_common.py", 0o444),
    "planiq-display-mark.png": (
        ROOT / "frontend/public/brand/planiq-display/planiq-display-mark.png",
        0o444,
    ),
}
STATIC_SOURCES = {
    "00_START_HER_KORT.txt": (USB / "00_START_HER_KORT.txt", 0o444),
    "01_START_CLIENTFLOW_USB.sh": (USB / "01_START_CLIENTFLOW_USB.sh", 0o755),
    "README_START_HER.txt": (USB / "README_START_HER.txt", 0o444),
    "Start ClientFlow.EXE": (USB / "Start ClientFlow.EXE", 0o555),
    "PlanIQ Flow.png": (USB / "planiq-flow-logo.png", 0o444),
}
ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(name: str, data: bytes, mode: int) -> tuple[str, bytes, int]:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe USB member path: {name}")
    return name, data, mode


def build(output: Path) -> tuple[int, str]:
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    entries: list[tuple[str, bytes, int]] = []
    for name, (source, mode) in STATIC_SOURCES.items():
        data = source.read_bytes()
        entries.append(_entry(name, data, mode))

    checksum_lines: list[str] = []
    for name, (source, mode) in PAYLOAD_SOURCES.items():
        data = source.read_bytes()
        entries.append(_entry(f"payload/{name}", data, mode))
        checksum_lines.append(f"{_sha256(data)}  payload/{name}")
    checksums = ("\n".join(checksum_lines) + "\n").encode("utf-8")
    entries.append(_entry("PAYLOAD_SHA256SUMS.txt", checksums, 0o444))

    top_checksums = []
    for name, data, _mode in sorted(entries):
        top_checksums.append(f"{_sha256(data)}  {name}")
    entries.append(_entry("USB_SHA256SUMS.txt", ("\n".join(top_checksums) + "\n").encode("utf-8"), 0o444))

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data, mode in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    raw = output.read_bytes()
    return len(raw), _sha256(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic ClientFlow V2 USB installer")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    size, digest = build(args.output.resolve())
    print(args.output.resolve())
    print(f"USB_SIZE={size}")
    print(f"USB_SHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
