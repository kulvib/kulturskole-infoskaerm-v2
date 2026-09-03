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


def test_catalog_1216_promotes_exact_1315_release_identity() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert data["catalog_sequence"] == 1216
    assert data["latest_stable"] == "1.3.15"
    assert data["default_install_version"] == "1.3.15"
    assert data["retention_policy"] == {
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }

    assert len(data["releases"]) == 1
    release = data["releases"][0]
    assert release["version"] == "1.3.15"
    assert release["client_version"] == "1.3.15"
    assert release["release_sequence"] == 1216
    assert release["release_id"] == "clientflow-1.3.15-seq-1216"
    assert release["revision"] == "clientflow-1.3.15-seq-1216"
    assert release["status"] == "stable"
    assert release["installable"] is True
    assert release["update_allowed"] is True
    assert release["rollback_allowed"] is False
    assert release["requires_reboot"] is True
    assert release["install_modes"] == ["fresh_install", "in_place_update"]
    assert release["min_current_version"] == "1.3.11"


def test_catalog_1216_rejects_1310_and_accepts_safe_1311_in_place_source() -> None:
    load_catalog.cache_clear()
    release = resolve_release("1.3.15")

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


def test_catalog_1216_matches_source_build_1315_1216_after_promotion() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    release = data["releases"][0]

    source_version = (ROOT / "client/VERSION").read_text(encoding="utf-8").strip()
    release_input = json.loads(
        (ROOT / "client/release/release-input.json").read_text(encoding="utf-8")
    )
    source_sequence = int(release_input["release_sequence"])

    # Promotion is permitted only after the exact candidate has passed CI,
    # manual approval and immutable 51M publication. Once promoted, source/build
    # identity and the runtime selection catalog must be exactly aligned.
    assert source_version == "1.3.15"
    assert source_sequence == 1216
    assert data["catalog_sequence"] == 1216
    assert source_sequence == data["catalog_sequence"]
    assert data["latest_stable"] == "1.3.15"
    assert data["default_install_version"] == "1.3.15"
    assert release["version"] == "1.3.15"
    assert release["release_sequence"] == 1216
    assert release["release_id"] == "clientflow-1.3.15-seq-1216"
    assert release["requires_reboot"] is True

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


def test_catalog_1216_resolvers_select_1315_for_update_and_fresh_install() -> None:
    load_catalog.cache_clear()
    update = resolve_release("1.3.15")
    fresh = resolve_fresh_install_release()

    for release in (update, fresh):
        assert release["version"] == "1.3.15"
        assert release["release_id"] == "clientflow-1.3.15-seq-1216"
        assert release["release_sequence"] == 1216
        assert release["status"] == "stable"
        assert release["requires_reboot"] is True

    assert update["update_allowed"] is True
    assert fresh["installable"] is True
    assert "in_place_update" in update["install_modes"]
    assert "fresh_install" in fresh["install_modes"]
