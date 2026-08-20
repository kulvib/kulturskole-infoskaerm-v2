from __future__ import annotations

import argparse
import hashlib
import re
import tempfile
from pathlib import Path

from clientflow_release_format.archive import read_bundle_artifacts_fd

from .bundle import extract_verified_payload, open_verified_bundle, verify_bundle
from .builder import _create_bundle
from .crypto import sha256_file
from .manifest import validate_manifest
from .runtime_artifacts import validate_runtime_artifacts
from .runtime_prepare import prepare_runtime


class ApprovalError(RuntimeError):
    pass


_APPROVAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,199}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def approve_bundle(
    candidate_bundle: Path,
    output_bundle: Path,
    *,
    approval_reference: str,
    expected_candidate_sha256: str,
    expected_installer_sha256: str,
    expected_source_commit: str,
) -> dict:
    """Promote one exact, verified CI candidate to deployable without signing keys."""
    approval_reference = approval_reference.strip()
    expected_candidate_sha256 = expected_candidate_sha256.strip().lower()
    expected_installer_sha256 = expected_installer_sha256.strip().lower()
    expected_source_commit = expected_source_commit.strip().lower()
    if not _APPROVAL_RE.fullmatch(approval_reference):
        raise ApprovalError("En gyldig, eksplicit approval_reference er påkrævet")
    if not _SHA256_RE.fullmatch(expected_candidate_sha256):
        raise ApprovalError("expected_candidate_sha256 skal være præcis SHA-256")
    if not _SHA256_RE.fullmatch(expected_installer_sha256):
        raise ApprovalError("expected_installer_sha256 skal være præcis SHA-256")
    if not _COMMIT_RE.fullmatch(expected_source_commit):
        raise ApprovalError("expected_source_commit skal være et fuldt Git commit-SHA")

    candidate_handle = None
    try:
        try:
            manifest, payload, _candidate_size, actual_candidate_sha256, candidate_handle = open_verified_bundle(
                candidate_bundle,
                require_deployable=False,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            raise ApprovalError(f"Kandidatbundlen er ugyldig: {exc}") from exc

        if actual_candidate_sha256 != expected_candidate_sha256:
            raise ApprovalError("Kandidatbundlens SHA-256 matcher ikke den eksplicit godkendte hash")

        installer_contract = manifest.get("fresh_installer") or {}
        if str(installer_contract.get("sha256") or "") != expected_installer_sha256:
            raise ApprovalError("Fresh installerens SHA-256 matcher ikke den eksplicit godkendte hash")
        try:
            _embedded_manifest, _embedded_payload, installer_bytes = read_bundle_artifacts_fd(
                candidate_handle.fileno()
            )
        except (OSError, ValueError, RuntimeError) as exc:
            raise ApprovalError(f"Fresh installer-medlemmet er ugyldigt: {exc}") from exc
        if (
            len(installer_bytes) != int(installer_contract.get("size") or 0)
            or hashlib.sha256(installer_bytes).hexdigest()
            != str(installer_contract.get("sha256") or "")
        ):
            raise ApprovalError("Fresh installer-medlemmet matcher ikke release candidate-manifestet")

        if manifest.get("deployable") is not False:
            raise ApprovalError("Inputbundlen skal være en ikke-deployable release candidate")
        approval = manifest.get("release_approval") or {}
        if approval.get("reference") not in {None, ""} or approval.get("candidate_sha256") not in {None, ""}:
            raise ApprovalError("Release candidate må ikke allerede have approval metadata")
        if manifest.get("runtime", {}).get("offline_wheelhouse_complete") is not True:
            raise ApprovalError("Godkendelse afvises: offline runtime/wheelhouse er ikke komplet")
        source = manifest.get("source") or {}
        if source.get("dirty") is not False:
            raise ApprovalError("Godkendelse afvises: kandidaten kommer ikke fra et rent commit")
        if source.get("commit") != expected_source_commit:
            raise ApprovalError("Godkendelse afvises: source commit matcher ikke det eksplicit forventede commit")

        try:
            validate_runtime_artifacts(payload, manifest)
            with tempfile.TemporaryDirectory(prefix="clientflow-approval-preflight-") as directory:
                release_root = extract_verified_payload(
                    payload,
                    Path(directory) / "payload",
                    expected_root=str(manifest["payload"]["root"]),
                )
                prepare_runtime(release_root, manifest)
        except (ValueError, RuntimeError, OSError) as exc:
            raise ApprovalError(f"Godkendelse afvises: runtime-preflight fejlede: {exc}") from exc

        approved = dict(manifest)
        approved["deployable"] = True
        approved["release_approval"] = {
            "reference": approval_reference,
            "candidate_sha256": actual_candidate_sha256,
        }
        validate_manifest(approved, require_deployable=True)

        with tempfile.NamedTemporaryFile(prefix="clientflow-payload-", suffix=".tar", delete=False) as temporary:
            temporary.write(payload)
            temporary.flush()
            payload_path = Path(temporary.name)
        with tempfile.NamedTemporaryFile(prefix="clientflow-installer-", suffix=".pyz", delete=False) as temporary:
            temporary.write(installer_bytes)
            temporary.flush()
            installer_path = Path(temporary.name)
        try:
            _create_bundle(
                output_bundle,
                approved,
                payload_path,
                installer_path,
                epoch=int(approved["source_date_epoch"]),
            )
        finally:
            payload_path.unlink(missing_ok=True)
            installer_path.unlink(missing_ok=True)

        verify_bundle(output_bundle, require_deployable=True)
        return approved
    finally:
        if candidate_handle is not None:
            candidate_handle.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Approve a verified ClientFlow release candidate without signing keys")
    parser.add_argument("candidate_bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--expected-installer-sha256", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--approve-release", action="store_true")
    args = parser.parse_args(argv)
    if not args.approve_release:
        raise SystemExit("Releasegodkendelse kræver --approve-release og udtrykkelig brugergodkendelse")
    approved = approve_bundle(
        args.candidate_bundle,
        args.output,
        approval_reference=args.approval_reference,
        expected_candidate_sha256=args.expected_candidate_sha256,
        expected_installer_sha256=args.expected_installer_sha256,
        expected_source_commit=args.expected_source_commit,
    )
    size, digest = sha256_file(args.output)
    installer_contract = approved["fresh_installer"]
    installer_size = int(installer_contract["size"])
    installer_digest = str(installer_contract["sha256"])
    print(args.output)
    print(f"BUNDLE_SIZE={size}")
    print(f"BUNDLE_SHA256={digest}")
    print(f"INSTALLER_SIZE={installer_size}")
    print(f"INSTALLER_SHA256={installer_digest}")
    return 0
