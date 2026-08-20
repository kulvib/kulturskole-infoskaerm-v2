#!/usr/bin/env python3
"""Fail closed unless the release builder runs with the repo-pinned toolchain."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import re

ROOT = Path(__file__).resolve().parents[1]


def _load_contract(repo: Path) -> dict[str, object]:
    path = repo / "client/release/release-build-toolchain.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported release-build toolchain schema")
    return data


def validate_toolchain(repo: Path) -> dict[str, str]:
    repo = repo.resolve()
    contract = _load_contract(repo)
    expected = {
        "python": str(contract["python"]),
        "pip": str(contract["pip"]),
        "setuptools": str(contract["setuptools"]),
    }
    actual = {
        "python": platform.python_version(),
        "pip": importlib.metadata.version("pip"),
        "setuptools": importlib.metadata.version("setuptools"),
    }
    for name, wanted in expected.items():
        if actual[name] != wanted:
            raise ValueError(
                f"Release-build toolchain mismatch for {name}: "
                f"expected {wanted}, got {actual[name]}"
            )

    pyproject = (repo / "client/runtime/pyproject.toml").read_text(encoding="utf-8")
    build_req = re.search(r'requires\s*=\s*\["setuptools==([^"\]]+)"\]', pyproject)
    if not build_req or build_req.group(1) != expected["setuptools"]:
        raise ValueError("client/runtime/pyproject.toml must pin the canonical setuptools version")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args()
    actual = validate_toolchain(args.repo)
    for name in ("python", "pip", "setuptools"):
        print(f"{name}={actual[name]}")
    print("RESULT: RELEASE BUILD TOOLCHAIN VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
