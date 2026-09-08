from __future__ import annotations

import json
from pathlib import Path

import pytest

from service1.clientflow_releases import (
    ClientFlowCatalogError,
    load_catalog,
    resolve_fresh_install_release,
    resolve_release,
    validate_release_compatibility,
)


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "backend/service1/clientflow_release_catalog.json"


def test_catalog_1219_promotes_exact_1318_release_identity() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert data["catalog_sequence"] == 1219
    assert data["latest_stable"] == "1.3.18"
    assert data["default_install_version"] == "1.3.18"
    assert data["retention_policy"] == {
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }

    assert len(data["releases"]) == 1
    release = data["releases"][0]
    assert release["version"] == "1.3.18"
    assert release["client_version"] == "1.3.18"
    assert release["release_sequence"] == 1219
    assert release["release_id"] == "clientflow-1.3.18-seq-1219"
    assert release["revision"] == "clientflow-1.3.18-seq-1219"
    assert release["status"] == "stable"
    assert release["installable"] is True
    assert release["update_allowed"] is True
    assert release["rollback_allowed"] is False
    assert release["requires_reboot"] is True
    assert release["install_modes"] == ["fresh_install", "in_place_update"]
    assert release["min_current_version"] == "1.3.11"


def test_catalog_1219_rejects_1310_and_accepts_safe_1311_in_place_source() -> None:
    load_catalog.cache_clear()
    release = resolve_release("1.3.18")

    with pytest.raises(ClientFlowCatalogError, match="kræver mindst ClientFlow 1.3.11"):
        validate_release_compatibility(
            release,
            current_version="1.3.10",
            ubuntu_version="26.04",
        )

    validate_release_compatibility(
        release,
        current_version="1.3.11",
        ubuntu_version="26.04",
    )


def test_catalog_1219_matches_current_source_and_allows_only_next_staged_identity() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    release = data["releases"][0]

    source_version = (ROOT / "client/VERSION").read_text(encoding="utf-8").strip()
    release_input = json.loads(
        (ROOT / "client/release/release-input.json").read_text(encoding="utf-8")
    )
    source_sequence = int(release_input["release_sequence"])
    source_tuple = tuple(int(part) for part in source_version.split("."))
    selected_tuple = tuple(int(part) for part in release["version"].split("."))

    assert data["catalog_sequence"] == 1219
    assert data["latest_stable"] == "1.3.18"
    assert data["default_install_version"] == "1.3.18"
    assert release["version"] == "1.3.18"
    assert release["release_sequence"] == 1219
    assert release["release_id"] == "clientflow-1.3.18-seq-1219"
    assert release["requires_reboot"] is True

    # The immutable 1.3.18/1219 release is already selected by the runtime
    # catalog. Any later source bytes must therefore use the next staged
    # source/build identity before a new candidate can be built.
    assert source_version == "1.3.19"
    assert source_sequence == 1220
    assert source_sequence == data["catalog_sequence"] + 1
    assert source_tuple > selected_tuple

    for field in (
        "bundle_sha256",
        "bundle_size",
        "approval_reference",
        "release_approval_reference",
        "candidate_sha256",
        "source_commit",
    ):
        assert field not in release


def test_catalog_1219_resolvers_select_1318_for_update_and_fresh_install() -> None:
    load_catalog.cache_clear()
    update = resolve_release("1.3.18")
    fresh = resolve_fresh_install_release()

    for release in (update, fresh):
        assert release["version"] == "1.3.18"
        assert release["release_id"] == "clientflow-1.3.18-seq-1219"
        assert release["release_sequence"] == 1219
        assert release["status"] == "stable"
        assert release["requires_reboot"] is True

    assert update["update_allowed"] is True
    assert fresh["installable"] is True
    assert "in_place_update" in update["install_modes"]
    assert "fresh_install" in fresh["install_modes"]


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

