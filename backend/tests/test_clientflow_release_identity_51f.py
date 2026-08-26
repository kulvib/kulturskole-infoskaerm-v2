from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[2]
VERSION_PATH = ROOT / "client/VERSION"
RELEASE_INPUT_PATH = ROOT / "client/release/release-input.json"
CATALOG_PATH = ROOT / "backend/service1/clientflow_release_catalog.json"
PYPROJECT_PATH = ROOT / "client/runtime/pyproject.toml"
HISTORICAL_RUNTIME_LOCK = ROOT / "client/runtime-artifacts.lock.json"


def _version() -> str:
    return VERSION_PATH.read_text(encoding="utf-8").strip()


def test_51f_source_build_identity_is_monotonic_and_catalog_never_leads_it() -> None:
    version = _version()
    release_input = json.loads(RELEASE_INPUT_PATH.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    source_sequence = int(release_input["release_sequence"])
    catalog_sequence = int(catalog["catalog_sequence"])
    source_tuple = tuple(int(part) for part in version.split("."))

    # Source/build identity is allowed to move exactly one release ahead while
    # candidate build, manual approval and immutable publication are pending.
    # The runtime catalog must never lead source/build identity.
    assert source_sequence >= catalog_sequence
    assert source_sequence - catalog_sequence in {0, 1}
    assert len(source_tuple) == 3

    assert len(catalog["releases"]) == 1
    selected = catalog["releases"][0]
    assert selected["version"] == catalog["latest_stable"]
    assert selected["version"] == catalog["default_install_version"]
    assert selected["release_sequence"] == catalog_sequence
    assert selected["release_id"] == f"clientflow-{selected['version']}-seq-{selected['release_sequence']}"
    assert selected["revision"] == selected["release_id"]

    selected_tuple = tuple(int(part) for part in selected["version"].split("."))
    assert selected_tuple <= source_tuple
    if source_sequence == catalog_sequence:
        assert selected_tuple == source_tuple
    else:
        assert selected_tuple < source_tuple


def test_51f_promoted_1311_is_fresh_baseline_and_blocks_1310_in_place_bootstrap() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    release = catalog["releases"][0]

    # 1.3.11/1212 is the first release containing the corrected activation/update
    # transaction implementation. It remains selectable for fresh install, but
    # must not advertise immutable 1.3.10 as a safe in-place predecessor.
    assert release["version"] == _version()
    assert release["version"] == catalog["latest_stable"]
    assert release["version"] == catalog["default_install_version"]
    assert release["min_current_version"] == "1.3.11"
    assert "fresh_install" in release["install_modes"]
    assert "in_place_update" in release["install_modes"]


def test_51f_runtime_wheel_version_is_dynamic_from_canonical_version_module() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert "version" not in project
    assert "version" in project["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "clientflow_runtime.version.VERSION"
    }

    result = subprocess.run(
        [sys.executable, "-c", "import clientflow_runtime; print(clientflow_runtime.__version__)"],
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "client/runtime")},
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.stdout.strip() == _version()


def test_51f_canonical_release_code_has_no_hardcoded_product_version() -> None:
    release_lib = ROOT / "client/release/lib/clientflow_release"
    for path in release_lib.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "1.2.0" not in text, path
        assert _version() not in text, path

    release_download = (ROOT / "client/runtime/clientflow_runtime/release_download.py").read_text(encoding="utf-8")
    assert 'from .version import VERSION' in release_download
    assert 'f"ClientFlow/{VERSION} system-agent"' in release_download
    assert "ClientFlow/1.2.0 system-agent" not in release_download

    runtime_prepare = (ROOT / "client/release/lib/clientflow_release/runtime_prepare.py").read_text(encoding="utf-8")
    assert "clientflow_runtime.__version__ == expected" in runtime_prepare
    assert "version('clientflow-runtime') == expected" in runtime_prepare
    assert 'str(manifest["version"])' in runtime_prepare


def test_51f_physical_1200_runtime_lock_remains_historical_not_current_authority() -> None:
    lock = json.loads(HISTORICAL_RUNTIME_LOCK.read_text(encoding="utf-8"))
    assert lock["release_id"] == "clientflow-1.2.0-seq-1200"
    assert lock["version"] == "1.2.0"
    assert any(item["file"].startswith("clientflow_runtime-1.2.0-") for item in lock["artifacts"])

    # release-ready.json is generated inside installed releases; a repo-root copy
    # would look like a second current release authority and must not be tracked.
    assert not (ROOT / "client/release-ready.json").exists()
