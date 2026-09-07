#!/usr/bin/env python3
"""Build a deterministic ClientFlow release candidate from the canonical v2 repo."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "client" / "release" / "lib"))
from clientflow_release.builder import build  # noqa: E402
from verify_release_build_toolchain import validate_toolchain  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--runtime-inputs", type=Path)
    args = parser.parse_args()

    repo = args.repo.resolve()
    validate_toolchain(repo)
    base_inputs = (args.runtime_inputs or (repo / "client" / "runtime-inputs")).resolve()
    if not base_inputs.is_dir():
        raise SystemExit(
            "Offline runtime-inputs mangler. Angiv --runtime-inputs med python-runtime-amd64.tar, wheelhouse/, platform/ og bootstrap/."
        )

    with tempfile.TemporaryDirectory(prefix="clientflow-runtime-inputs-") as tmp:
        runtime_inputs = Path(tmp)
        shutil.copytree(base_inputs, runtime_inputs, dirs_exist_ok=True)
        wheelhouse = runtime_inputs / "wheelhouse"
        wheelhouse.mkdir(parents=True, exist_ok=True)
        # The ClientFlow wheel is always rebuilt from canonical source. A stale
        # prebuilt runtime wheel must never override the repo being released.
        for old in wheelhouse.glob("clientflow_runtime-*.whl"):
            old.unlink()
        build_dir = runtime_inputs / ".build"
        build_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--ignore-requires-python",
                "--no-build-isolation",
                "--wheel-dir",
                str(build_dir),
                str(repo / "client" / "runtime"),
            ],
            check=True,
        )
        wheel = next(build_dir.glob("clientflow_runtime-*.whl"))
        shutil.copy2(wheel, wheelhouse / wheel.name)
        result = build(
            repo,
            args.output_dir.resolve(),
            runtime_inputs=runtime_inputs,
            allow_dirty=args.allow_dirty,
        )

    print(result["bundle"])
    print(result["installer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
