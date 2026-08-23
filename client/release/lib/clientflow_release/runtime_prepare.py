from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess

from .archive import inspect_payload_tar, safe_extract_payload
from .crypto import sha256_file
from .filesystem import atomic_write_bytes, atomic_write_json, fsync_directory


class RuntimePreparationError(RuntimeError):
    pass


ACTIVE_RUNTIME_PYTHON = "/opt/clientflow/active/runtime/bin/python"
CLIENTFLOW_ENTRYPOINTS = (
    "clientflow-status-agent",
    "clientflow-calendar",
    "clientflow-display-agent",
    "clientflow-display-runtime",
    "clientflow-display-power-broker",
    "clientflow-display-platform-prepare",
    "clientflow-livestream-agent",
    "clientflow-livestream-broker",
    "clientflow-livestream-producer",
    "clientflow-livestream-uploader",
    "clientflow-remote-desktop-agent",
    "clientflow-remote-desktop-capture",
    "clientflow-remote-desktop-input-broker",
    "clientflow-terminal-agent",
    "clientflow-standard-terminal-broker",
    "clientflow-root-terminal-broker",
    "clientflow-system-agent",
    "clientflow-system-broker",
    "clientflow-runtime-diagnostics",
)


def _run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
    )
    if result.returncode != 0:
        raise RuntimePreparationError(
            f"Kommando fejlede ({result.returncode}): {' '.join(command)}\n{result.stdout[-4000:]}"
        )
    return result


def _ensure_runtime_python(runtime: Path) -> Path:
    python3 = runtime / "bin/python3"
    if not python3.is_file() or python3.is_symlink():
        raise RuntimePreparationError("Den medfølgende Python-runtime mangler bin/python3")
    python = runtime / "bin/python"
    if python.exists() or python.is_symlink():
        metadata = python.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimePreparationError("Den medfølgende Python-runtime har ugyldig bin/python")
    shutil.copy2(python3, python)
    if not python.is_file() or python.is_symlink():
        raise RuntimePreparationError("Runtime bin/python kunne ikke materialiseres")
    return python


def _validate_systemd_entrypoint_inventory(release_root: Path) -> None:
    prefix = "/opt/clientflow/active/runtime/bin/"
    required: set[str] = set()
    systemd_root = release_root / "client-runtime/systemd"
    for unit in systemd_root.glob("*.service"):
        for line in unit.read_text(encoding="utf-8").splitlines():
            if line.startswith("ExecStart=" + prefix):
                required.add(line.split(prefix, 1)[1].split()[0])
    missing = sorted(required.difference(CLIENTFLOW_ENTRYPOINTS))
    if missing:
        raise RuntimePreparationError(
            "Systemd refererer runtime-entrypoints uden relocation-kontrakt: " + ", ".join(missing)
        )


def _rewrite_clientflow_entrypoints(runtime: Path) -> None:
    fixed_shebang = f"#!{ACTIVE_RUNTIME_PYTHON}\n".encode("utf-8")
    for name in CLIENTFLOW_ENTRYPOINTS:
        path = runtime / "bin" / name
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise RuntimePreparationError(f"Installeret runtime mangler entrypoint: {name}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimePreparationError(f"Installeret runtime-entrypoint er ugyldigt: {name}")
        data = path.read_bytes()
        line_end = data.find(b"\n")
        if line_end < 0 or not data.startswith(b"#!"):
            raise RuntimePreparationError(f"Installeret runtime-entrypoint mangler shebang: {name}")
        try:
            interpreter = data[2:line_end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimePreparationError(f"Installeret runtime-entrypoint har ugyldig shebang: {name}") from exc
        if not interpreter.endswith("/runtime/bin/python"):
            raise RuntimePreparationError(
                f"Installeret runtime-entrypoint peger på uventet Python: {name}"
            )
        atomic_write_bytes(
            path,
            fixed_shebang + data[line_end + 1 :],
            mode=stat.S_IMODE(metadata.st_mode),
        )


def prepare_runtime(release_root: Path, manifest: dict) -> None:
    runtime = manifest["runtime"]
    if runtime.get("offline_wheelhouse_complete") is not True:
        raise RuntimePreparationError("Releasepayloaden mangler komplet offline runtime")
    input_root = release_root / "runtime-inputs"
    python_tar = input_root / "python-runtime-amd64.tar"
    wheelhouse = input_root / "wheelhouse"
    if not python_tar.is_file() or not wheelhouse.is_dir():
        raise RuntimePreparationError("Runtimeinput mangler")
    declared = {item["file"]: item for item in runtime.get("artifacts") or []}
    python_metadata = declared.get("python-runtime-amd64.tar")
    if not python_metadata:
        raise RuntimePreparationError("Manifestet mangler Python-runtime-hash")
    python_size, python_digest = sha256_file(python_tar)
    if python_size != int(python_metadata["size"]) or python_digest != python_metadata["sha256"]:
        raise RuntimePreparationError("Python-runtime-hash matcher ikke")
    wheel_declared = {name: value for name, value in declared.items() if name != "python-runtime-amd64.tar"}
    for wheel in wheelhouse.glob("*.whl"):
        metadata = wheel_declared.get(wheel.name)
        if not metadata:
            raise RuntimePreparationError(f"Udeklareret wheel: {wheel.name}")
        size, digest = sha256_file(wheel)
        if size != int(metadata["size"]) or digest != metadata["sha256"]:
            raise RuntimePreparationError(f"Wheel-hash matcher ikke: {wheel.name}")
    if set(wheel_declared) != {item.name for item in wheelhouse.glob("*.whl")}:
        raise RuntimePreparationError("Wheelhouse matcher ikke manifestet")

    python_extract = release_root / ".python-extract"
    inspect_payload_tar(python_tar, expected_root="python-3.13.14")
    extracted = safe_extract_payload(python_tar, python_extract, expected_root="python-3.13.14")
    runtime_root = release_root / "runtime"
    os.replace(extracted, runtime_root)
    python_extract.rmdir()
    runtime_python = _ensure_runtime_python(runtime_root)
    version = _run(
        [str(runtime_python), "-c", "import platform; print(platform.python_version())"],
        timeout=30,
    ).stdout.strip()
    if version != "3.13.14":
        raise RuntimePreparationError(f"Python-runtime har forkert version: {version}")

    pip_wheels = sorted(wheelhouse.glob("pip-*.whl"))
    if not pip_wheels:
        raise RuntimePreparationError("Wheelhouse mangler pip-wheel")
    # Run pip directly from its pinned wheel and install into the relocatable
    # bundled interpreter. A venv is deliberately not created: CPython venv
    # creates lib64/bin symlinks and absolute staging paths that are invalid
    # after the staged release directory is atomically published.
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(pip_wheels[-1]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_NO_CACHE_DIR": "1",
    }
    result = subprocess.run(
        [
            str(runtime_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--only-binary=:all:",
            "--no-compile",
            f"--find-links={wheelhouse}",
            "clientflow-runtime==" + manifest["version"],
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=600,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimePreparationError(result.stdout[-4000:])
    _validate_systemd_entrypoint_inventory(release_root)
    _rewrite_clientflow_entrypoints(runtime_root)
    _run(
        [
            str(runtime_python),
            "-c",
            (
                "import sys; import clientflow_runtime; "
                "from importlib.metadata import version; "
                "expected=sys.argv[1]; "
                "assert clientflow_runtime.__version__ == expected; "
                "assert version('clientflow-runtime') == expected"
            ),
            str(manifest["version"]),
        ],
        timeout=30,
    )
    metadata = {
        "schema_version": 1,
        "version": manifest["version"],
        "release_id": manifest["release_id"],
        "release_sequence": manifest["release_sequence"],
        "python": version,
    }
    atomic_write_json(release_root / "release-ready.json", metadata, mode=0o444)
    for path in release_root.rglob("*"):
        if path.is_symlink():
            raise RuntimePreparationError(f"Symlink fundet efter runtimeforberedelse: {path}")
    fsync_directory(release_root)
