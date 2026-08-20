"""Canonical, deployment-bundled ClientFlow release catalog helpers.

The runtime reads the same single-release policy bundled with the backend so
Control Room and clients share one canonical release contract.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("clientflow_release_catalog.json")
SELECTABLE_STATUSES = {"stable", "supported"}
KNOWN_STATUSES = SELECTABLE_STATUSES | {"deprecated", "blocked"}


class ClientFlowCatalogError(RuntimeError):
    pass


def _version_tuple(value: str) -> tuple[int, ...]:
    raw = str(value or "").strip().lstrip("vV")
    try:
        parts = tuple(int(part) for part in raw.split("."))
    except (TypeError, ValueError) as exc:
        raise ClientFlowCatalogError(f"Ugyldig ClientFlow-version: {value!r}") from exc
    if not parts or any(part < 0 for part in parts):
        raise ClientFlowCatalogError(f"Ugyldig ClientFlow-version: {value!r}")
    return parts


def compare_versions(left: str, right: str) -> int:
    a = list(_version_tuple(left))
    b = list(_version_tuple(right))
    width = max(len(a), len(b))
    a.extend([0] * (width - len(a)))
    b.extend([0] * (width - len(b)))
    return (a > b) - (a < b)


def _ubuntu_version_tuple(value: str | None) -> tuple[int, int] | None:
    match = re.search(r"(?<!\d)(\d{2})\.(\d{2})(?!\d)", str(value or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _release_supports_ubuntu(release: dict[str, Any], ubuntu_version: str | None) -> bool:
    actual = _ubuntu_version_tuple(ubuntu_version)
    if actual is None:
        return True

    policy = release.get("ubuntu_compatibility") or {}
    if policy:
        if policy.get("policy") != "ubuntu-desktop-lts-minimum":
            raise ClientFlowCatalogError("Ukendt Ubuntu-kompatibilitetspolitik")
        minimum = _ubuntu_version_tuple(str(policy.get("minimum_lts_version") or ""))
        if minimum is None or minimum[1] != 4:
            raise ClientFlowCatalogError("Ubuntu-kompatibilitetspolitikken mangler gyldig minimum_lts_version")
        year, month = actual
        min_year, _ = minimum
        return month == 4 and year >= min_year and (year - min_year) % 2 == 0

    exact = [
        _ubuntu_version_tuple(str(value))
        for value in (release.get("ubuntu_versions") or [])
        if str(value).strip()
    ]
    return not exact or actual in exact


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - deployment contract catches this
        raise ClientFlowCatalogError("ClientFlow-versionskataloget kunne ikke læses") from exc

    if data.get("manifest_schema") != 4 or data.get("channel") != "canonical-release-catalog":
        raise ClientFlowCatalogError("ClientFlow-versionskataloget har forkert schema/kanal")
    if not isinstance(data.get("catalog_sequence"), int) or data["catalog_sequence"] <= 0:
        raise ClientFlowCatalogError("ClientFlow-versionskataloget mangler catalog_sequence")
    releases = data.get("releases")
    if not isinstance(releases, list) or not releases:
        raise ClientFlowCatalogError("ClientFlow-versionskataloget er tomt")

    versions: set[str] = set()
    for release in releases:
        version = str(release.get("version") or "").strip()
        status = str(release.get("status") or "").strip().lower()
        _version_tuple(version)
        if version in versions:
            raise ClientFlowCatalogError(f"Dubleret ClientFlow-version i kataloget: {version}")
        versions.add(version)
        if status not in KNOWN_STATUSES:
            raise ClientFlowCatalogError(f"Ukendt release-status for {version}: {status}")
        policy = release.get("ubuntu_compatibility") or {}
        if policy:
            if policy.get("policy") != "ubuntu-desktop-lts-minimum":
                raise ClientFlowCatalogError(f"Ukendt Ubuntu-kompatibilitetspolitik for {version}")
            minimum = _ubuntu_version_tuple(str(policy.get("minimum_lts_version") or ""))
            if minimum is None or minimum[1] != 4:
                raise ClientFlowCatalogError(f"Ugyldig minimum_lts_version for {version}")
            if policy.get("requires_platform_preflight") is not True:
                raise ClientFlowCatalogError(f"Ubuntu LTS-politikken kræver platformspreflight for {version}")

    latest = str(data.get("latest_stable") or "").strip()
    latest_release = next((item for item in releases if item.get("version") == latest), None)
    if not latest_release or latest_release.get("status") != "stable":
        raise ClientFlowCatalogError("latest_stable peger ikke på en stabil release")
    return data


def resolve_release(requested_version: str | None) -> dict[str, Any]:
    catalog = load_catalog()
    requested = str(requested_version or "latest").strip().lower()
    version = catalog["latest_stable"] if requested in {"", "latest", "stable"} else requested.lstrip("v")
    release = next((item for item in catalog["releases"] if item.get("version") == version), None)
    if release is None:
        raise ClientFlowCatalogError(f"ClientFlow-version {version} findes ikke")
    status = str(release.get("status") or "").lower()
    if status not in SELECTABLE_STATUSES or release.get("update_allowed") is not True:
        reason = release.get("block_reason") or release.get("deprecation_reason") or "Versionen kan ikke installeres"
        raise ClientFlowCatalogError(str(reason))
    return dict(release)



def validate_release_compatibility(
    release: dict[str, Any],
    *,
    current_version: str | None,
    ubuntu_version: str | None,
) -> None:
    """Reject a known-incompatible update/rollback target.

    Fresh factory installation is validated by the autoinstall selector. This
    helper protects remote update orders when the backend has enough client
    telemetry to make an authoritative decision. Unknown telemetry is left to
    the signed ClientFlow worker, which performs the same check locally.
    """
    current = str(current_version or "").strip().lstrip("vV")
    minimum = str(release.get("min_current_version") or "").strip().lstrip("vV")
    maximum = str(release.get("max_current_version") or "").strip().lstrip("vV")
    if current and minimum and compare_versions(current, minimum) < 0:
        raise ClientFlowCatalogError(
            f"ClientFlow {release['version']} kræver mindst ClientFlow {minimum}; klienten kører {current}"
        )
    if current and maximum and compare_versions(current, maximum) > 0:
        raise ClientFlowCatalogError(
            f"ClientFlow {release['version']} kan højst installeres fra ClientFlow {maximum}; klienten kører {current}"
        )

    actual_ubuntu = str(ubuntu_version or "").strip()
    if actual_ubuntu and not _release_supports_ubuntu(release, actual_ubuntu):
        policy = release.get("ubuntu_compatibility") or {}
        if policy:
            supported = f"Ubuntu Desktop LTS fra {policy.get('minimum_lts_version')}"
        else:
            exact = [str(value).strip() for value in release.get("ubuntu_versions") or [] if str(value).strip()]
            supported = f"Ubuntu {', '.join(exact)}"
        raise ClientFlowCatalogError(
            f"ClientFlow {release['version']} understøtter {supported}; klienten rapporterer {actual_ubuntu}"
        )

def public_catalog() -> dict[str, Any]:
    catalog = load_catalog()
    releases = []
    for item in catalog["releases"]:
        releases.append({
            "version": item.get("version"),
            "status": item.get("status"),
            "release_sequence": item.get("release_sequence"),
            "revision": item.get("revision"),
            "client_version_patch": item.get("client_version_patch"),
            "created_at": item.get("created_at"),
            "installable": item.get("installable") is True,
            "update_allowed": item.get("update_allowed") is True,
            "rollback_allowed": item.get("rollback_allowed") is True,
            "requires_explicit_downgrade": item.get("requires_explicit_downgrade") is True,
            "requires_reboot": item.get("requires_reboot") is True,
            "min_current_version": item.get("min_current_version"),
            "max_current_version": item.get("max_current_version"),
            "ubuntu_versions": item.get("ubuntu_versions") or [],
            "ubuntu_compatibility": item.get("ubuntu_compatibility") or {},
            "block_reason": item.get("block_reason"),
            "deprecation_reason": item.get("deprecation_reason"),
            "notes": item.get("notes") or [],
        })
    return {
        "catalog_sequence": catalog["catalog_sequence"],
        "latest_stable": catalog["latest_stable"],
        "default_install_version": catalog.get("default_install_version") or catalog["latest_stable"],
        "retention_policy": catalog.get("retention_policy") or {},
        "releases": releases,
    }


class ClientFlowArtifactUnavailable(ClientFlowCatalogError):
    """The release exists, but lacks immutable artifact authority metadata."""


def deployment_release_snapshot(release: dict[str, Any]) -> dict[str, Any]:
    """Return immutable artifact/approval identity for one deployment authorization.

    Deployment authorization must never trust artifact identity supplied by an
    admin request or an unprivileged client.  The values are read only from the
    backend release catalog and copied into the durable deployment row.

    The current catalog has not yet been migrated to the final artifact schema;
    this helper therefore accepts both the future nested ``artifact`` shape and
    the legacy flat names, but fails closed when the actual bytes are not
    identified by SHA-256 and size.
    """
    artifact = release.get("artifact") if isinstance(release.get("artifact"), dict) else {}
    approval = release.get("release_approval") if isinstance(release.get("release_approval"), dict) else {}

    release_id = str(release.get("release_id") or release.get("revision") or "").strip()
    bundle_sha256 = str(artifact.get("sha256") or release.get("bundle_sha256") or "").strip().lower()
    raw_size = artifact.get("size") if artifact.get("size") is not None else release.get("bundle_size")
    approval_reference = str(
        release.get("release_approval_reference") or approval.get("reference") or ""
    ).strip()
    candidate_sha256 = str(
        release.get("release_candidate_sha256") or approval.get("candidate_sha256") or ""
    ).strip().lower() or None
    source_commit = str(release.get("source_commit") or approval.get("source_commit") or "").strip() or None

    try:
        bundle_size = int(raw_size)
    except (TypeError, ValueError):
        bundle_size = 0

    missing: list[str] = []
    if not release_id:
        missing.append("release_id/revision")
    if not re.fullmatch(r"[0-9a-f]{64}", bundle_sha256):
        missing.append("bundle_sha256")
    if bundle_size <= 0:
        missing.append("bundle_size")
    if not approval_reference:
        missing.append("release_approval_reference")
    if candidate_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", candidate_sha256):
        missing.append("release_candidate_sha256")
    if source_commit is not None and not re.fullmatch(r"[0-9a-f]{40,64}", source_commit):
        missing.append("source_commit")
    if missing:
        raise ClientFlowArtifactUnavailable(
            "ClientFlow-releasen mangler autoritativ artifact metadata: " + ", ".join(missing)
        )

    return {
        "target_release_id": release_id,
        "bundle_sha256": bundle_sha256,
        "bundle_size": bundle_size,
        "release_approval_reference": approval_reference,
        "release_candidate_sha256": candidate_sha256,
        "source_commit": source_commit,
    }
