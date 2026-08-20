from pathlib import Path

import pytest

from clientflow_release_format.constants import (
    ARTIFACT_TYPE_RUNTIME_RELEASE,
    CHANNEL,
    INSTALL_MODE_FRESH,
    INSTALL_MODE_UPDATE,
    MANIFEST_SCHEMA,
)
from clientflow_release_format.manifest import ManifestError

ROOT = Path(__file__).resolve().parents[2]


def test_step51c_has_one_backend_importable_canonical_release_format_package():
    manifest_source = (ROOT / "client/release/lib/clientflow_release/manifest.py").read_text()
    constants_source = (ROOT / "client/release/lib/clientflow_release/constants.py").read_text()
    builder_source = (ROOT / "client/release/lib/clientflow_release/builder.py").read_text()
    assert "clientflow_release_format.manifest" in manifest_source
    assert "clientflow_release_format.constants" in constants_source
    assert 'repo / "backend/clientflow_release_format"' in builder_source
    assert MANIFEST_SCHEMA == 6
    assert CHANNEL == "clientflow-runtime-release"
    assert ARTIFACT_TYPE_RUNTIME_RELEASE == "runtime_release"


def test_runtime_release_format_replaces_fresh_only_with_explicit_install_modes():
    builder = (ROOT / "client/release/lib/clientflow_release/builder.py").read_text()
    manifest = (ROOT / "backend/clientflow_release_format/manifest.py").read_text()
    assert '"artifact_type": ARTIFACT_TYPE_RUNTIME_RELEASE' in builder
    assert '"install_modes": [INSTALL_MODE_FRESH, INSTALL_MODE_UPDATE]' in builder
    assert '"fresh_only"' not in builder
    assert "fresh_only" not in manifest
    assert INSTALL_MODE_FRESH == "fresh_install"
    assert INSTALL_MODE_UPDATE == "in_place_update"


def test_fresh_and_update_paths_request_their_own_install_mode():
    cli = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text()
    transaction = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text()
    assert "required_install_mode=INSTALL_MODE_FRESH" in cli
    assert "install_mode=INSTALL_MODE_FRESH" in cli
    assert "install_mode: str = INSTALL_MODE_UPDATE" in transaction
    assert "required_install_mode=install_mode" in transaction
