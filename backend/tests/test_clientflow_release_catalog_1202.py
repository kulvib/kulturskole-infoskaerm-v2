from __future__ import annotations

import json
from pathlib import Path

from service1.clientflow_releases import (
    load_catalog,
    resolve_fresh_install_release,
    resolve_release,
)


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "backend/service1/clientflow_release_catalog.json"


def test_catalog_1202_promotes_exact_131_release_identity() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert data["catalog_sequence"] == 1202
    assert data["latest_stable"] == "1.3.1"
    assert data["default_install_version"] == "1.3.1"
    assert data["retention_policy"] == {
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }

    assert len(data["releases"]) == 1
    release = data["releases"][0]
    assert release["version"] == "1.3.1"
    assert release["client_version"] == "1.3.1"
    assert release["release_sequence"] == 1202
    assert release["release_id"] == "clientflow-1.3.1-seq-1202"
    assert release["revision"] == "clientflow-1.3.1-seq-1202"
    assert release["status"] == "stable"
    assert release["installable"] is True
    assert release["update_allowed"] is True
    assert release["rollback_allowed"] is False
    assert release["install_modes"] == ["fresh_install", "in_place_update"]
    assert release["min_current_version"] == "1.3.0"


def test_catalog_1202_matches_source_release_identity_and_keeps_bytes_out_of_catalog() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    release = data["releases"][0]

    assert (ROOT / "client/VERSION").read_text(encoding="utf-8").strip() == "1.3.1"
    release_input = json.loads(
        (ROOT / "client/release/release-input.json").read_text(encoding="utf-8")
    )
    assert release_input["release_sequence"] == 1202

    for field in (
        "bundle_sha256",
        "bundle_size",
        "approval_reference",
        "release_approval_reference",
        "candidate_sha256",
        "source_commit",
    ):
        assert field not in release


def test_catalog_1202_resolvers_select_131_for_update_and_fresh_install() -> None:
    load_catalog.cache_clear()
    update = resolve_release("1.3.1")
    fresh = resolve_fresh_install_release()

    for release in (update, fresh):
        assert release["version"] == "1.3.1"
        assert release["release_id"] == "clientflow-1.3.1-seq-1202"
        assert release["release_sequence"] == 1202
        assert release["status"] == "stable"

    assert update["update_allowed"] is True
    assert fresh["installable"] is True
    assert "in_place_update" in update["install_modes"]
    assert "fresh_install" in fresh["install_modes"]
