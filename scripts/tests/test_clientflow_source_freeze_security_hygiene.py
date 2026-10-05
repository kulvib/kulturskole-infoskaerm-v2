from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_source_freeze_has_no_repo_overlay_duplicate_tree() -> None:
    assert not (ROOT / "repo-overlay").exists(), (
        "repo-overlay is a stale duplicate source tree and must not be present in a "
        "ClientFlow source-freeze candidate"
    )



def test_source_freeze_has_no_backend_path_overlay_tree() -> None:
    leaked = [name for name in ("service1", "tests") if (ROOT / name).exists()]
    assert leaked == [], (
        "backend delivery paths leaked into repository root instead of backend/: "
        + ", ".join(leaked)
    )

def test_source_freeze_has_no_delivery_package_artifacts() -> None:
    """Delivery-only bundle metadata must never become canonical source."""
    forbidden_root_artifacts = {
        "CHANGED_FILES.txt",
        "DELETIONS.txt",
        "DELIVERY_MANIFEST.sha256",
        "README.txt",
        "SHA256SUMS_PACKAGE.txt",
        "clientflow-factory-post-reboot-readiness-os-update-ci-fix-CHANGED_FILES.txt",
        "clientflow-factory-post-reboot-readiness-os-update-ci-fix-DELETE_FILES.txt",
        "clientflow-factory-post-reboot-readiness-os-update-ci-fix-TEST_RESULTS.txt",
    }
    leaked = sorted(name for name in forbidden_root_artifacts if (ROOT / name).exists())
    leaked.extend(path.name for path in sorted(ROOT.glob("*.patch")))
    leaked.extend(path.name for path in sorted(ROOT.glob("CLIENTFLOW_*_FIX_PACKAGE_README.txt")))
    assert leaked == [], (
        "delivery-only artifact leaked into canonical source: " + ", ".join(leaked)
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



def test_brace_expansion_audit_false_positive_waiver_is_exact_and_short_lived() -> None:
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    brace = lock["packages"]["node_modules/brace-expansion"]
    assert brace["version"] == "1.1.21"

    allowlist = json.loads(
        (ROOT / "frontend" / "dependency-audit-allowlist.json").read_text(encoding="utf-8")
    )
    exceptions = allowlist.get("exceptions", [])
    brace_exceptions = [item for item in exceptions if item.get("package") == "brace-expansion"]
    assert brace_exceptions == [
        {
            "package": "brace-expansion",
            "advisories": [
                "GHSA-q2hr-2g5m-vwhr",
                "GHSA-qhr7-859c-m2p7",
                "GHSA-6j4f-fj2g-mc7p",
            ],
            "expires": "2026-10-07",
            "scope": (
                "npm audit registry-feed false positive for exact patched "
                "brace-expansion 1.1.21 only"
            ),
            "replacementPlan": (
                "Remove this exception as soon as npm audit stops reporting these three "
                "advisories against brace-expansion 1.1.21; do not extend without "
                "re-verifying the published affected ranges."
            ),
        }
    ]

def test_1331_1232_source_freeze_leads_promoted_1330_1231_by_one_and_keeps_update_closed() -> None:
    assert (ROOT / "client" / "VERSION").read_text(encoding="utf-8").strip() == "1.3.31"
    release_input = json.loads(
        (ROOT / "client" / "release" / "release-input.json").read_text(encoding="utf-8")
    )
    assert release_input["release_sequence"] == 1232
    assert release_input["runtime_python"] == "3.13.14"

    catalog = json.loads(
        (ROOT / "backend" / "service1" / "clientflow_release_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert catalog["catalog_sequence"] == 1231
    assert catalog["latest_stable"] == "1.3.30"
    assert catalog["default_install_version"] == "1.3.30"
    selected = catalog["releases"][0]
    assert selected["release_id"] == "clientflow-1.3.30-seq-1231"
    assert selected["installable"] is True
    assert selected["update_allowed"] is False
    assert selected["install_modes"] == ["fresh_install"]
    assert all(item.get("release_sequence") != 1228 for item in catalog["releases"])

    rejection = (ROOT / "CLIENTFLOW_1.3.28_1229_SECURITY_REPLACEMENT.md").read_text(encoding="utf-8")
    assert "CVE-2026-101918" in rejection
    assert "1.3.27 / 1228" in rejection
    assert "must not be catalog-promoted" in rejection
    assert "PyJWT `2.15.1`" in rejection

    identity = (ROOT / "CLIENTFLOW_1.3.31_1232_SOURCE_IDENTITY.md").read_text(encoding="utf-8")
    freeze = (ROOT / "CLIENTFLOW_1.3.31_1232_SOURCE_FREEZE_CLOSURE.md").read_text(encoding="utf-8")
    changed = (ROOT / "CHANGED_FILES_1331_1232_SOURCE_FREEZE.txt").read_text(encoding="utf-8")
    assert "source-frozen candidate" in identity
    assert "not built, physically accepted, published or catalog-promoted" in identity
    assert "1.3.30/1231 physical fresh-install acceptance failed" in identity
    assert "PASS for source freeze" in freeze
    assert "exact 40-character source-freeze SHA" in freeze
    assert "No physical acceptance, immutable publication or catalog promotion is claimed" in freeze
    assert "CLIENTFLOW_1.3.31_1232_SOURCE_FREEZE_CLOSURE.md" in changed
    assert "scripts/tests/test_clientflow_source_freeze_security_hygiene.py" in changed

    promotion = (ROOT / "CLIENTFLOW_1.3.30_1231_FRESH_INSTALL_CATALOG_PROMOTION.md").read_text(
        encoding="utf-8"
    )
    assert "fresh-install-only catalog promotion" in promotion
    assert "6995280649c68bbd201dee73edde7d6a1f71eaa5" in promotion
    assert "b3fbe2530907d86e581704a58819c01f17d8ca2f8842a0d2f6e35f9bb9138cd7" in promotion
    assert "PUBLICATION_VERIFIED_OK" in promotion
    assert "Physical acceptance is **PENDING**" in promotion

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
    assert "CLIENTFLOW_1.3.25_1226_SOURCE_REFREEZE_TERMINAL_UX_CLOSURE.md" in seen
    assert "CHANGED_FILES_1325_1226_TERMINAL_UX_CLOSURE.txt" in seen
    assert "CLIENTFLOW_1.3.25_1226_SOURCE_REFREEZE_UNUSED_FILE_HYGIENE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1325_1226_UNUSED_FILE_HYGIENE_CLOSURE.txt" in seen
    assert "scripts/tests/test_clientflow_1226_unused_file_hygiene.py" in seen
    assert "CHANGED_FILES_1324_1225_SOURCE_FREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.24_1225_CATALOG_PROMOTION.md" in seen
    assert "CHANGED_FILES_1324_1225_CATALOG_PROMOTION.txt" in seen
    assert "CLIENTFLOW_1.3.25_1226_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.25_1226_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1325_1226_SOURCE_FREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.25_1226_CATALOG_PROMOTION.md" in seen
    assert "CHANGED_FILES_1325_1226_CATALOG_PROMOTION.txt" in seen
    assert "CLIENTFLOW_1.3.26_1227_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.26_1227_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1326_1227_SOURCE_FREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.26_1227_CATALOG_PROMOTION.md" in seen
    assert "CHANGED_FILES_1326_1227_CATALOG_PROMOTION.txt" in seen
    assert "CLIENTFLOW_1.3.27_1228_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.27_1228_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1327_1228_SOURCE_FREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.27_1228_SOURCE_REFREEZE_PYTHON_RUNTIME_BRIDGE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1327_1228_SOURCE_REFREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.27_1228_FINAL_SOURCE_REFREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1327_1228_FINAL_SOURCE_REFREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.27_1228_POST_MAINTENANCE_FINAL_SOURCE_REFREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1327_1228_POST_MAINTENANCE_FINAL_SOURCE_REFREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.28_1229_SECURITY_REPLACEMENT.md" in seen
    assert "CLIENTFLOW_1.3.28_1229_CATALOG_PROMOTION.md" in seen
    assert "CHANGED_FILES_1328_1229_CATALOG_PROMOTION.txt" in seen
    assert "CLIENTFLOW_1.3.29_1230_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.29_1230_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1329_1230_SOURCE_FREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.29_1230_FRESH_INSTALL_CATALOG_PROMOTION.md" in seen
    assert "CHANGED_FILES_1329_1230_FRESH_INSTALL_CATALOG_PROMOTION.txt" in seen
    assert "CLIENTFLOW_1.3.30_1231_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.30_1231_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1330_1231_SOURCE_FREEZE.txt" in seen
    assert "CLIENTFLOW_1.3.30_1231_FRESH_INSTALL_CATALOG_PROMOTION.md" in seen
    assert "CHANGED_FILES_1330_1231_FRESH_INSTALL_CATALOG_PROMOTION.txt" in seen
    assert "CLIENTFLOW_1.3.31_1232_SOURCE_IDENTITY.md" in seen
    assert "CLIENTFLOW_1.3.31_1232_SOURCE_FREEZE_CLOSURE.md" in seen
    assert "CHANGED_FILES_1331_1232_SOURCE_FREEZE.txt" in seen


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


def test_1325_1226_refreeze_contains_no_known_unused_runtime_or_template_files() -> None:
    forbidden = (
        "BASE_BLOBS.txt",
        "client/runtime/clientflow_runtime/release_download.py",
        "client/config-examples/domain-credential.json",
        "client/config-examples/identity.json",
        "client/config-examples/root-grant.json",
    )
    leaked = [relative for relative in forbidden if (ROOT / relative).exists()]
    assert leaked == [], "known unused pre-1226 files remain: " + ", ".join(leaked)


def test_1327_1228_initial_freeze_is_superseded_by_python_runtime_bridge_refreeze() -> None:
    initial = (ROOT / "CLIENTFLOW_1.3.27_1228_SOURCE_FREEZE_CLOSURE.md").read_text(
        encoding="utf-8"
    )
    refreeze = (
        ROOT / "CLIENTFLOW_1.3.27_1228_SOURCE_REFREEZE_PYTHON_RUNTIME_BRIDGE_CLOSURE.md"
    ).read_text(encoding="utf-8")

    assert "SUPERSEDED BEFORE BUILD" in initial
    assert "d3d598aa5f51a36d87992d7635ea504e6440f881" in refreeze
    assert "#1047" in refreeze
    assert "36474336723" in refreeze
    assert "sequence-1228 runtime-input transport" in refreeze
    assert "runtime Python: `3.13.14`" in refreeze
    assert "Python 3.13.15" in refreeze
    assert "source release sequence" in refreeze and "catalog sequence" in refreeze


def test_1327_1228_final_refreeze_supersedes_pre_audit_source_authority() -> None:
    identity = (ROOT / "CLIENTFLOW_1.3.27_1228_SOURCE_IDENTITY.md").read_text(
        encoding="utf-8"
    )
    bridge = (
        ROOT / "CLIENTFLOW_1.3.27_1228_SOURCE_REFREEZE_PYTHON_RUNTIME_BRIDGE_CLOSURE.md"
    ).read_text(encoding="utf-8")
    historical_final = (
        ROOT / "CLIENTFLOW_1.3.27_1228_FINAL_SOURCE_REFREEZE_CLOSURE.md"
    ).read_text(encoding="utf-8")
    final = (
        ROOT / "CLIENTFLOW_1.3.27_1228_POST_MAINTENANCE_FINAL_SOURCE_REFREEZE_CLOSURE.md"
    ).read_text(encoding="utf-8")

    assert "CLIENTFLOW_1.3.27_1228_POST_MAINTENANCE_FINAL_SOURCE_REFREEZE_CLOSURE.md" in identity
    assert "SUPERSEDED BEFORE FINAL BUILD" in bridge
    assert "SUPERSEDED BEFORE BUILD" in historical_final
    assert "CLIENTFLOW_1.3.27_1228_POST_MAINTENANCE_FINAL_SOURCE_REFREEZE_CLOSURE.md" in historical_final
    assert "cd0482434f18866a52ceddefe12f1464219d9b71" in final
    assert "#1161" in final
    assert "36734756428" in final
    assert "embedded runtime Python: `3.13.14`" in final
    assert "Python `3.13.15`" in final
    assert "source-SHA-qualified" in final
    assert "expected_source_sha" in final
    assert "source release sequence: `1228`" in final
    assert "catalog sequence: `1227`" in final

