from __future__ import annotations

import json
from pathlib import Path

import pytest

from service1.clientflow_releases import (
    ClientFlowCatalogError,
    load_catalog,
    resolve_fresh_install_release,
    resolve_release,
)


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "backend/service1/clientflow_release_catalog.json"


def test_catalog_1231_promotes_exact_1330_fresh_install_identity() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert data["catalog_sequence"] == 1231
    assert data["latest_stable"] == "1.3.30"
    assert data["default_install_version"] == "1.3.30"
    assert data["retention_policy"] == {
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }

    assert len(data["releases"]) == 1
    release = data["releases"][0]
    assert release["version"] == "1.3.30"
    assert release["client_version"] == "1.3.30"
    assert release["release_sequence"] == 1231
    assert release["release_id"] == "clientflow-1.3.30-seq-1231"
    assert release["revision"] == "clientflow-1.3.30-seq-1231"
    assert release["status"] == "stable"
    assert release["installable"] is True
    assert release["update_allowed"] is False
    assert release["rollback_allowed"] is False
    assert release["requires_reboot"] is True
    assert release["install_modes"] == ["fresh_install"]
    assert "min_current_version" not in release
    assert "ikke fysisk verificeret" in release["block_reason"]


def test_catalog_1231_aligns_exact_1330_1231_frozen_source_and_selector() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    release = data["releases"][0]

    source_version = (ROOT / "client/VERSION").read_text(encoding="utf-8").strip()
    release_input = json.loads(
        (ROOT / "client/release/release-input.json").read_text(encoding="utf-8")
    )

    assert source_version == "1.3.30"
    assert release_input["release_sequence"] == 1231
    assert release_input["runtime_python"] == "3.13.14"
    assert data["catalog_sequence"] == 1231
    assert data["latest_stable"] == "1.3.30"
    assert data["default_install_version"] == "1.3.30"
    assert data["latest_stable"] == source_version
    assert release["release_id"] == "clientflow-1.3.30-seq-1231"
    assert all(item.get("release_sequence") != 1228 for item in data["releases"])
    assert all(item.get("version") != "1.3.27" for item in data["releases"])

    for field in (
        "bundle_sha256",
        "bundle_size",
        "approval_reference",
        "release_approval_reference",
        "candidate_sha256",
        "source_commit",
    ):
        assert field not in release


def test_catalog_1231_fresh_install_resolves_but_update_resolution_is_fail_closed() -> None:
    load_catalog.cache_clear()
    fresh = resolve_fresh_install_release()

    assert fresh["version"] == "1.3.30"
    assert fresh["release_id"] == "clientflow-1.3.30-seq-1231"
    assert fresh["release_sequence"] == 1231
    assert fresh["status"] == "stable"
    assert fresh["installable"] is True
    assert fresh["update_allowed"] is False
    assert fresh["install_modes"] == ["fresh_install"]

    with pytest.raises(ClientFlowCatalogError, match="kun frigivet til fresh install"):
        resolve_release("1.3.30")


def test_catalog_rejects_update_allowed_without_in_place_update_mode(tmp_path: Path, monkeypatch) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["releases"][0]["update_allowed"] = True
    test_catalog = tmp_path / "clientflow_release_catalog.json"
    test_catalog.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("service1.clientflow_releases.CATALOG_PATH", test_catalog)
    load_catalog.cache_clear()
    try:
        with pytest.raises(ClientFlowCatalogError, match="update_allowed uden in_place_update"):
            load_catalog()
    finally:
        load_catalog.cache_clear()


@pytest.mark.parametrize("requested", [None, "", "   ", "latest", "LATEST", "stable", "StAbLe"])
def test_release_resolver_rejects_implicit_latest_aliases(requested: str | None) -> None:
    load_catalog.cache_clear()
    with pytest.raises(ClientFlowCatalogError, match="konkret katalogversion"):
        resolve_release(requested)


def test_catalog_requires_explicit_default_fresh_install_version(tmp_path: Path, monkeypatch) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data.pop("default_install_version", None)
    test_catalog = tmp_path / "clientflow_release_catalog.json"
    test_catalog.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("service1.clientflow_releases.CATALOG_PATH", test_catalog)
    load_catalog.cache_clear()
    try:
        with pytest.raises(ClientFlowCatalogError, match="mangler default_install_version"):
            load_catalog()
    finally:
        load_catalog.cache_clear()


def test_catalog_rejects_default_fresh_install_version_that_is_not_in_catalog(tmp_path: Path, monkeypatch) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["default_install_version"] = "9.9.9"
    test_catalog = tmp_path / "clientflow_release_catalog.json"
    test_catalog.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("service1.clientflow_releases.CATALOG_PATH", test_catalog)
    load_catalog.cache_clear()
    try:
        with pytest.raises(ClientFlowCatalogError, match="findes ikke i releasekataloget"):
            load_catalog()
    finally:
        load_catalog.cache_clear()


def test_catalog_rejects_default_that_is_not_fresh_installable(tmp_path: Path, monkeypatch) -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    data["releases"][0]["installable"] = False
    test_catalog = tmp_path / "clientflow_release_catalog.json"
    test_catalog.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("service1.clientflow_releases.CATALOG_PATH", test_catalog)
    load_catalog.cache_clear()
    try:
        with pytest.raises(ClientFlowCatalogError, match="installérbar fresh-install release"):
            load_catalog()
    finally:
        load_catalog.cache_clear()
