from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_source_freeze_has_no_repo_overlay_duplicate_tree() -> None:
    assert not (ROOT / "repo-overlay").exists(), (
        "repo-overlay is a stale duplicate source tree and must not be present in a "
        "ClientFlow source-freeze candidate"
    )


def test_nanoid_high_severity_advisory_is_fixed_without_waiver() -> None:
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    nanoid = lock["packages"]["node_modules/nanoid"]

    assert nanoid["version"] == "3.3.18"
    assert nanoid["resolved"] == "https://registry.npmjs.org/nanoid/-/nanoid-3.3.18.tgz"
    assert nanoid["integrity"] == (
        "sha512-DTg4MJbGMWkfi6VZFdNt2/caMbQy4Ou+Op/hJQvGEWcnVfoA1QA+"
        "xzRKAzw9jD6+GVOOeYr/mIcuDSdug6F6+w=="
    )

    allowlist = json.loads(
        (ROOT / "frontend" / "dependency-audit-allowlist.json").read_text(encoding="utf-8")
    )
    for exception in allowlist.get("exceptions", []):
        assert exception.get("package") != "nanoid"
        assert "GHSA-2v37-7h3g-55p8" not in exception.get("advisories", [])


def test_1324_1225_staged_source_leads_1323_1224_catalog_by_one() -> None:
    assert (ROOT / "client" / "VERSION").read_text(encoding="utf-8").strip() == "1.3.24"
    release_input = json.loads(
        (ROOT / "client" / "release" / "release-input.json").read_text(encoding="utf-8")
    )
    assert release_input["release_sequence"] == 1225

    catalog = json.loads(
        (ROOT / "backend" / "service1" / "clientflow_release_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert catalog["catalog_sequence"] == 1224
    assert release_input["release_sequence"] == catalog["catalog_sequence"] + 1
    assert catalog["latest_stable"] == "1.3.23"
    assert catalog["default_install_version"] == "1.3.23"
    assert catalog["releases"][0]["release_id"] == "clientflow-1.3.23-seq-1224"


def test_source_checksum_manifest_matches_current_files() -> None:
    import hashlib

    manifest = ROOT / "SHA256SUMS.txt"
    seen: set[str] = set()
    for raw_line in manifest.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        digest, relative = raw_line.split("  ", 1)
        assert relative not in seen, f"duplicate SHA256SUMS entry: {relative}"
        seen.add(relative)
        target = ROOT / relative
        assert target.is_file(), f"SHA256SUMS target missing: {relative}"
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        assert actual == digest, f"SHA256SUMS drift: {relative}"

    assert "VALIDATION.txt" in seen
    assert "CLIENTFLOW_1.3.22_1223_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.22_1223_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CLIENTFLOW_1.3.22_1223_CATALOG_PROMOTION.md" in seen
    assert "CHANGED_FILES_1322_1223_CATALOG_PROMOTION.txt" in seen
    assert "CLIENTFLOW_1.3.23_1224_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.23_1224_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1323_1224_SOURCE_FREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.23_1224_SOURCE_REFREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1323_1224_SOURCE_REFREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.23_1224_CATALOG_PROMOTION.md" in seen
    assert "CHANGED_FILES_1323_1224_CATALOG_PROMOTION.txt" in seen
    assert "CLIENTFLOW_1.3.24_1225_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.24_1225_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1324_1225_SOURCE_FREEZE.txt" in seen


def test_1323_1224_initial_freeze_is_explicitly_superseded_before_build() -> None:
    initial = (ROOT / "CLIENTFLOW_1.3.23_1224_SOURCE_FREEZE_CLOSURE.md").read_text(
        encoding="utf-8"
    )
    refreeze = (ROOT / "CLIENTFLOW_1.3.23_1224_SOURCE_REFREEZE_CLOSURE.md").read_text(
        encoding="utf-8"
    )

    assert "SUPERSEDED BEFORE BUILD" in initial
    assert "a7dbbfaea404733d00a0070e62c644cd5460e6eb" in refreeze
    assert "#758" in refreeze
    assert "35449745659" in refreeze
    assert "sequence-1224 runtime-input transport" in refreeze
    assert "source release sequence" in refreeze and "catalog sequence" in refreeze
