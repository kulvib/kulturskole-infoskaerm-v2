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


def test_catalog_1212_promotes_exact_1311_release_identity() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert data["catalog_sequence"] == 1212
    assert data["latest_stable"] == "1.3.11"
    assert data["default_install_version"] == "1.3.11"
    assert data["retention_policy"] == {
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }

    assert len(data["releases"]) == 1
    release = data["releases"][0]
    assert release["version"] == "1.3.11"
    assert release["client_version"] == "1.3.11"
    assert release["release_sequence"] == 1212
    assert release["release_id"] == "clientflow-1.3.11-seq-1212"
    assert release["revision"] == "clientflow-1.3.11-seq-1212"
    assert release["status"] == "stable"
    assert release["installable"] is True
    assert release["update_allowed"] is True
    assert release["rollback_allowed"] is False
    assert release["install_modes"] == ["fresh_install", "in_place_update"]
    assert release["min_current_version"] == "1.3.11"


def test_catalog_1212_rejects_1310_as_unsafe_in_place_source() -> None:
    load_catalog.cache_clear()
    release = resolve_release("1.3.11")

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


def test_catalog_1212_matches_promoted_source_and_keeps_byte_authority_out_of_catalog() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    release = data["releases"][0]

    source_version = (ROOT / "client/VERSION").read_text(encoding="utf-8").strip()
    release_input = json.loads(
        (ROOT / "client/release/release-input.json").read_text(encoding="utf-8")
    )

    # Catalog promotion is allowed only after immutable publication and
    # independent deep verification in the canonical store. Selector identity
    # must now match the already-built source identity.
    assert source_version == "1.3.11"
    assert int(release_input["release_sequence"]) == 1212
    assert data["catalog_sequence"] == int(release_input["release_sequence"])
    assert data["latest_stable"] == source_version
    assert data["default_install_version"] == source_version
    assert release["version"] == source_version
    assert release["release_sequence"] == int(release_input["release_sequence"])
    assert release["release_id"] == "clientflow-1.3.11-seq-1212"

    # Exact approved byte identity remains authority of the immutable 51M store
    # and is deliberately not copied into the policy catalog.
    for field in (
        "bundle_sha256",
        "bundle_size",
        "approval_reference",
        "release_approval_reference",
        "candidate_sha256",
        "source_commit",
    ):
        assert field not in release


def test_catalog_1212_resolvers_select_1311_for_update_and_fresh_install() -> None:
    load_catalog.cache_clear()
    update = resolve_release("1.3.11")
    fresh = resolve_fresh_install_release()

    for release in (update, fresh):
        assert release["version"] == "1.3.11"
        assert release["release_id"] == "clientflow-1.3.11-seq-1212"
        assert release["release_sequence"] == 1212
        assert release["status"] == "stable"

    assert update["update_allowed"] is True
    assert fresh["installable"] is True
    assert "in_place_update" in update["install_modes"]
    assert "fresh_install" in fresh["install_modes"]
