from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

from .constants import CHANNEL, DOMAIN_NAMES, INTEGRITY_ALGORITHM, MANIFEST_SCHEMA, PRODUCT

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_RELEASE_ID_RE = re.compile(r"^clientflow-(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-seq-([1-9]\d*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_APPROVAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,199}$")


class ManifestError(ValueError):
    pass


def load_json_object(path: Path, *, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ManifestError("Manifestet er for stort")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("Manifestet er ikke gyldig UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ManifestError("Manifestet skal være et JSON-objekt")
    return value


def _require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestError(f"{name} er ugyldig")
    return value


def _require_sha(value: object, name: str) -> str:
    text = str(value or "")
    if not _SHA256_RE.fullmatch(text):
        raise ManifestError(f"{name} er ikke SHA-256")
    return text


def validate_manifest(manifest: Mapping[str, Any], *, require_deployable: bool) -> dict[str, Any]:
    data = dict(manifest)
    allowed_keys = {
        "manifest_schema", "product", "channel", "version", "release_id", "release_sequence",
        "source_date_epoch", "fresh_only", "deployable", "integrity_algorithm", "release_approval",
        "source", "payload", "runtime", "platform", "credential_domains", "activation",
    }
    unknown = set(data) - allowed_keys
    if unknown:
        raise ManifestError(f"Manifestet indeholder ukendte felter: {sorted(unknown)}")
    if data.get("manifest_schema") != MANIFEST_SCHEMA:
        raise ManifestError("Manifestet har forkert schema")
    if data.get("product") != PRODUCT or data.get("channel") != CHANNEL:
        raise ManifestError("Manifestets produkt eller kanal er ugyldig")
    version = str(data.get("version") or "")
    if not _VERSION_RE.fullmatch(version):
        raise ManifestError("Manifestets version er ugyldig")
    release_id = str(data.get("release_id") or "")
    match = _RELEASE_ID_RE.fullmatch(release_id)
    if not match or ".".join(match.group(i) for i in (1, 2, 3)) != version:
        raise ManifestError("release_id matcher ikke versionen")
    sequence = _require_int(data.get("release_sequence"), "release_sequence", minimum=1)
    if int(match.group(4)) != sequence:
        raise ManifestError("release_id matcher ikke release_sequence")
    _require_int(data.get("source_date_epoch"), "source_date_epoch", minimum=1)
    if data.get("fresh_only") is not True:
        raise ManifestError("Manifestet skal være fresh-only")
    if data.get("integrity_algorithm") != INTEGRITY_ALGORITHM:
        raise ManifestError("Manifestets integritetsalgoritme er ugyldig")

    deployable = data.get("deployable")
    if not isinstance(deployable, bool):
        raise ManifestError("Manifestets deployable-gate mangler")
    if require_deployable and deployable is not True:
        raise ManifestError("Releasen er ikke deployable")

    approval = data.get("release_approval")
    if not isinstance(approval, dict) or set(approval) != {"reference", "candidate_sha256"}:
        raise ManifestError("Manifestets release_approval-kontrakt er ugyldig")
    approval_reference = approval.get("reference")
    candidate_sha256 = approval.get("candidate_sha256")
    if deployable is True:
        if not _APPROVAL_RE.fullmatch(str(approval_reference or "").strip()):
            raise ManifestError("En deployable release kræver en gyldig release approval reference")
        _require_sha(candidate_sha256, "release_approval.candidate_sha256")
    else:
        if approval_reference not in {None, ""} or candidate_sha256 not in {None, ""}:
            raise ManifestError("Et ikke-deployable build må ikke have release approval metadata")

    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise ManifestError("Manifestets payload mangler")
    if payload.get("file") != "clientflow-payload.tar" or payload.get("format") != "tar":
        raise ManifestError("Manifestets payloadformat er ugyldigt")
    root = str(payload.get("root") or "")
    if PurePosixPath(root).name != root or root != f"clientflow-{version}":
        raise ManifestError("Manifestets payload-root er ugyldig")
    _require_int(payload.get("size"), "payload.size", minimum=1)
    _require_sha(payload.get("sha256"), "payload.sha256")

    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        raise ManifestError("Manifestets runtime-kontrakt mangler")
    if runtime.get("python") != "3.13.14":
        raise ManifestError("Runtime Python skal være 3.13.14")
    if runtime.get("architecture") != "amd64":
        raise ManifestError("Runtimearkitekturen skal være amd64")
    artifacts = runtime.get("artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(item, dict) for item in artifacts):
        raise ManifestError("Runtimeartifact-listen er ugyldig")
    seen_artifacts: set[str] = set()
    for item in artifacts:
        name = str(item.get("file") or "")
        if not name or PurePosixPath(name).name != name or name in seen_artifacts:
            raise ManifestError("Runtimeartifact-navn er ugyldigt eller dubleret")
        seen_artifacts.add(name)
        _require_int(item.get("size"), f"runtime.artifacts[{name}].size", minimum=1)
        _require_sha(item.get("sha256"), f"runtime.artifacts[{name}].sha256")
    if runtime.get("offline_wheelhouse_complete") not in {True, False}:
        raise ManifestError("Runtime wheelhouse-gate mangler")
    if deployable is True and runtime.get("offline_wheelhouse_complete") is not True:
        raise ManifestError("En deployable release kræver komplet offline wheelhouse")

    platform = data.get("platform")
    if not isinstance(platform, dict) or platform != {
        "os": "ubuntu-desktop-lts",
        "minimum_lts": "26.04",
        "architecture": "amd64",
        "requires_preflight": True,
    }:
        raise ManifestError("Manifestets platformkontrakt er ugyldig")

    credentials = data.get("credential_domains")
    if credentials != list(DOMAIN_NAMES):
        raise ManifestError("Manifestets credential-domæner er ugyldige")
    activation = data.get("activation")
    if not isinstance(activation, dict) or activation.get("automatic") is not False:
        raise ManifestError("Releasen må ikke aktivere automatisk")
    if activation.get("requires_manual_approval") is not True:
        raise ManifestError("Aktivering skal kræve manuel godkendelse")
    if activation.get("automatic_reboot") is not False:
        raise ManifestError("Releasen må ikke genstarte automatisk")
    timeout = _require_int(activation.get("health_timeout_seconds"), "activation.health_timeout_seconds", minimum=30)
    if timeout > 900:
        raise ManifestError("Health timeout er for høj")
    source = data.get("source")
    if not isinstance(source, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit") or "")):
        raise ManifestError("Manifestets source commit er ugyldig")
    if not isinstance(source.get("dirty"), bool):
        raise ManifestError("Manifestets source dirty-gate mangler")
    if deployable is True and source.get("dirty") is not False:
        raise ManifestError("En deployable release skal bygges fra et rent commit")
    return data
