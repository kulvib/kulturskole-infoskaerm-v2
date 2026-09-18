from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "client/bootstrap/clientflow_bootstrap_common.py"
FACTORY = ROOT / "client/bootstrap/clientflow-factory-prepare"


def _load_common(name: str):
    spec = importlib.util.spec_from_file_location(name, COMMON)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _capture_launcher(monkeypatch, tmp_path: Path, *, title: str, command: str) -> Path:
    common = _load_common(f"clientflow_bootstrap_common_{title.replace(' ', '_')}")
    launcher = tmp_path / "launcher"

    def write_launcher(path: Path, content: str, *, mode: int) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)

    monkeypatch.setattr(common, "_atomic_root_file", write_launcher)
    common.install_terminal_launcher(launcher, title=title, command=command)
    return launcher


def test_terminal_launcher_defers_runtime_status_expansion_and_executes_via_ptyxis(
    monkeypatch, tmp_path: Path
) -> None:
    command = (
        "printf '%s\\n' 'INNER_START'; "
        "false; rc=$?; "
        "printf 'INNER_RC=%s\\n' \"$rc\"; "
        "exit \"$rc\""
    )
    launcher = _capture_launcher(
        monkeypatch,
        tmp_path,
        title="01 Klient klargøring",
        command=command,
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ptyxis = fake_bin / "ptyxis"
    ptyxis.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "case \"${1-}\" in --title=*) shift ;; *) exit 91 ;; esac\n"
        "[ \"${1-}\" = -- ] || exit 92\n"
        "shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    ptyxis.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    result = subprocess.run(
        [str(launcher)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env=env,
        timeout=10,
    )

    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert "INNER_START" in lines
    assert "INNER_RC=1" in lines
    assert "unbound variable" not in result.stderr.lower()

    source = launcher.read_text(encoding="utf-8")
    assert "RUN=" not in source
    assert source.index("command -v ptyxis") < source.index("command -v x-terminal-emulator")
    assert "exec ptyxis --title=" in source
    assert " -- bash -lc " in source


def test_terminal_launcher_generic_x_terminal_fallback_preserves_runtime_status(
    monkeypatch, tmp_path: Path
) -> None:
    command = "false; rc=$?; printf 'FALLBACK_RC=%s\\n' \"$rc\"; exit \"$rc\""
    launcher = _capture_launcher(
        monkeypatch,
        tmp_path,
        title="02 Aktiver ClientFlow",
        command=command,
    )

    fake_bin = tmp_path / "fallback-bin"
    fake_bin.mkdir()
    (fake_bin / "bash").symlink_to(Path("/bin/bash"))
    terminal = fake_bin / "x-terminal-emulator"
    terminal.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "[ \"${1-}\" = -T ] || exit 93\n"
        "shift 2\n"
        "[ \"${1-}\" = -e ] || exit 94\n"
        "shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    terminal.chmod(0o755)

    result = subprocess.run(
        [str(launcher)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        timeout=10,
    )

    assert result.returncode == 1
    assert "FALLBACK_RC=1" in result.stdout.splitlines()
    assert "unbound variable" not in result.stderr.lower()


def test_both_operator_desktop_flows_use_the_safe_shared_terminal_launcher() -> None:
    source = FACTORY.read_text(encoding="utf-8")
    assert source.count("install_terminal_launcher(") == 2
    assert 'title="01 Klient klargøring"' in source
    assert 'title="02 Aktiver ClientFlow"' in source
    assert source.count("rc=$?") == 2
    assert source.count("exit $rc") == 2
