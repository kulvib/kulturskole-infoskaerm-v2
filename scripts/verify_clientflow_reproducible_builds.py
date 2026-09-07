#!/usr/bin/env python3
"""Require two independent ClientFlow release builds to be byte-identical."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_STATIC_FILES = {"clientflow-payload.tar", "manifest.candidate.json", "SHA256SUMS"}


def _sha(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def _manifest(directory: Path) -> dict[str, object]:
    return json.loads((directory / "manifest.candidate.json").read_text(encoding="utf-8"))


def verify(
    repo: Path,
    left: Path,
    right: Path,
    expected_source_sha: str,
    expected_source_date_epoch: int,
    runtime_inputs_transport_sha256: str,
    output_record: Path,
) -> dict[str, object]:
    if not SHA_RE.fullmatch(expected_source_sha):
        raise ValueError("Expected source SHA must be a full lowercase Git SHA")
    if not SHA256_RE.fullmatch(runtime_inputs_transport_sha256):
        raise ValueError("Runtime-input transport SHA-256 is invalid")
    version = (repo / "client/VERSION").read_text(encoding="utf-8").strip()
    release_input = json.loads((repo / "client/release/release-input.json").read_text(encoding="utf-8"))
    sequence = int(release_input["release_sequence"])
    release_id = f"clientflow-{version}-seq-{sequence}"
    candidate = f"{release_id}-candidate.tar"
    installer = f"clientflow-installer-{version}.pyz"
    expected_files = EXPECTED_STATIC_FILES | {candidate, installer}

    actual_left = {p.name for p in left.iterdir() if p.is_file()}
    actual_right = {p.name for p in right.iterdir() if p.is_file()}
    if actual_left != expected_files or actual_right != expected_files:
        raise ValueError(
            f"Release build output set mismatch: left={sorted(actual_left)} right={sorted(actual_right)}"
        )

    artifacts: dict[str, dict[str, object]] = {}
    for name in sorted(expected_files):
        left_path = left / name
        right_path = right / name
        left_size, left_sha = _sha(left_path)
        right_size, right_sha = _sha(right_path)
        if left_size != right_size or left_sha != right_sha:
            raise ValueError(f"Release builds are not byte-identical for {name}")
        artifacts[name] = {"size": left_size, "sha256": left_sha}

    left_manifest = _manifest(left)
    right_manifest = _manifest(right)
    if left_manifest != right_manifest:
        raise ValueError("Candidate manifests differ")
    manifest = left_manifest
    if manifest.get("release_id") != release_id or manifest.get("version") != version:
        raise ValueError("Candidate release identity mismatch")
    if int(manifest.get("release_sequence") or -1) != sequence:
        raise ValueError("Candidate release sequence mismatch")
    if manifest.get("source_date_epoch") != expected_source_date_epoch:
        raise ValueError("Candidate SOURCE_DATE_EPOCH mismatch")
    source = manifest.get("source") or {}
    if source.get("commit") != expected_source_sha or source.get("dirty") is not False:
        raise ValueError("Candidate source provenance mismatch")
    if manifest.get("deployable") is not False:
        raise ValueError("Unapproved release build must not be deployable")

    payload = manifest.get("payload") or {}
    payload_record = artifacts["clientflow-payload.tar"]
    if payload.get("size") != payload_record["size"] or payload.get("sha256") != payload_record["sha256"]:
        raise ValueError("Payload descriptor does not match reproducible payload bytes")
    fresh_installer = manifest.get("fresh_installer") or {}
    installer_record = artifacts[installer]
    if fresh_installer.get("file") != installer:
        raise ValueError("Fresh-installer filename mismatch")
    if fresh_installer.get("size") != installer_record["size"] or fresh_installer.get("sha256") != installer_record["sha256"]:
        raise ValueError("Fresh-installer descriptor does not match reproducible installer bytes")

    with tarfile.open(left / candidate, mode="r:") as tf:
        member = tf.getmember(installer)
        embedded = tf.extractfile(member)
        if embedded is None:
            raise ValueError("Embedded fresh installer is unreadable")
        h = hashlib.sha256()
        embedded_size = 0
        while chunk := embedded.read(1024 * 1024):
            embedded_size += len(chunk)
            h.update(chunk)
    if embedded_size != installer_record["size"] or h.hexdigest() != installer_record["sha256"]:
        raise ValueError("Embedded fresh installer differs from reproducible loose installer output")

    toolchain = json.loads((repo / "client/release/release-build-toolchain.json").read_text(encoding="utf-8"))
    record = {
        "schema_version": 1,
        "release_id": release_id,
        "version": version,
        "release_sequence": sequence,
        "source_commit": expected_source_sha,
        "source_date_epoch": expected_source_date_epoch,
        "runtime_inputs_transport_sha256": runtime_inputs_transport_sha256,
        "build_toolchain": {
            "python": toolchain["python"],
            "pip": toolchain["pip"],
            "setuptools": toolchain["setuptools"],
        },
        "reproducible": True,
        "artifacts": artifacts,
    }
    output_record.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-source-date-epoch", type=int, required=True)
    parser.add_argument("--runtime-inputs-transport-sha256", required=True)
    parser.add_argument("--output-record", type=Path, required=True)
    args = parser.parse_args()
    record = verify(
        args.repo.resolve(),
        args.left.resolve(),
        args.right.resolve(),
        args.expected_source_sha,
        args.expected_source_date_epoch,
        args.runtime_inputs_transport_sha256,
        args.output_record.resolve(),
    )
    candidate = f"{record['release_id']}-candidate.tar"
    print(f"candidate_sha256={record['artifacts'][candidate]['sha256']}")
    print("RESULT: TWO INDEPENDENT RELEASE BUILDS ARE BYTE-IDENTICAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
