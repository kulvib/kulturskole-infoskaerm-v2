#!/usr/bin/env python3
"""Executable operational gate for one unapproved ClientFlow release candidate.

The candidate remains deployable=false. This gate materializes its exact payload,
installs the exact offline runtime, imports every console entrypoint, validates all
release-owned systemd command paths/accounts/unit references, applies managed
placeholders into a synthetic root, and runs the target host's systemd parser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "client" / "release" / "lib"))

from clientflow_release.bundle import extract_verified_payload, open_verified_bundle  # noqa: E402
from clientflow_release.runtime_artifacts import validate_runtime_artifacts  # noqa: E402
from clientflow_release.runtime_prepare import prepare_runtime  # noqa: E402
from clientflow_release.systemd_contract import validate_release_systemd_contract  # noqa: E402
from clientflow_release.transaction import Layout, _apply_definitions, _validate_prepared_release_tree  # noqa: E402


class CandidateGateError(RuntimeError):
    pass


def _sha256(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def _exact_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if len(matches) != 1:
        raise CandidateGateError(f"Forventede præcis én {pattern} i {root}, fandt {len(matches)}")
    path = matches[0]
    if not path.is_file() or path.is_symlink():
        raise CandidateGateError(f"Candidate artifact er ikke en regulær fil: {path}")
    return path


def _git_head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", result.stdout.strip()):
        raise CandidateGateError("Kunne ikke fastslå exact Git source commit")
    return result.stdout.strip()


def _verify_source_identity(repo: Path, manifest: dict) -> None:
    version = (repo / "client/VERSION").read_text(encoding="utf-8").strip()
    release_input = json.loads((repo / "client/release/release-input.json").read_text(encoding="utf-8"))
    sequence = int(release_input["release_sequence"])
    expected_release_id = f"clientflow-{version}-seq-{sequence}"
    expected = {
        "version": version,
        "release_sequence": sequence,
        "release_id": expected_release_id,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise CandidateGateError(f"Candidate matcher ikke repo source identity: {key}")
    if manifest.get("deployable") is not False:
        raise CandidateGateError("Release-build candidate må aldrig være deployable")
    source = manifest.get("source") or {}
    if source.get("commit") != _git_head(repo) or source.get("dirty") is not False:
        raise CandidateGateError("Candidate source provenance matcher ikke exact clean checkout")
    runtime = manifest.get("runtime") or {}
    if runtime.get("python") != release_input.get("runtime_python"):
        raise CandidateGateError("Candidate bundled runtime Python matcher ikke release-input")
    platform_contract = manifest.get("platform") or {}
    if (
        platform_contract.get("minimum_lts") != release_input.get("minimum_ubuntu_lts")
        or platform_contract.get("architecture") != release_input.get("architecture")
    ):
        raise CandidateGateError("Candidate platform contract matcher ikke release-input")


def _verify_installer_on_host(installer: Path, manifest: dict, system_python: Path) -> None:
    if not system_python.is_file() or not os.access(system_python, os.X_OK):
        raise CandidateGateError(f"System Python mangler: {system_python}")
    expected = manifest.get("fresh_installer") or {}
    size, digest = _sha256(installer)
    if installer.name != expected.get("file") or size != expected.get("size") or digest != expected.get("sha256"):
        raise CandidateGateError("Separat installer output matcher ikke candidate fresh_installer descriptor")
    result = subprocess.run(
        [str(system_python), "-I", str(installer), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0 or "ClientFlow trusted runtime-release installer" not in result.stdout:
        raise CandidateGateError(
            "Embedded fresh installer kan ikke starte under target host /usr/bin/python3:\n" + result.stdout[-4000:]
        )


def _verify_embedded_display_platform_artifact(release_root: Path) -> None:
    runtime_python = release_root / "runtime/bin/python"
    code = (
        "from pathlib import Path; import sys; "
        "from clientflow_runtime.display_platform_prepare import _load_chrome_artifact, _verify_deb_metadata; "
        "p,a=_load_chrome_artifact(Path(sys.argv[1])); _verify_deb_metadata(p,a); "
        "print(p.name)"
    )
    result = subprocess.run(
        [str(runtime_python), "-I", "-c", code, str(release_root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        raise CandidateGateError(
            "Embedded Display platform artifact metadata kan ikke valideres på target host:\n"
            + result.stdout[-4000:]
        )


def _verify_display_platform_install_on_host(release_root: Path) -> dict[str, str]:
    if os.geteuid() != 0:
        raise CandidateGateError("Executable Display platform-install gate kræver root på ephemeral CI host")
    runtime_python = release_root / "runtime/bin/python"
    code = r'''
import json
from pathlib import Path
import sys
from clientflow_runtime.display_platform_prepare import (
    _active_google_repo_files,
    _ensure_exact_chrome,
    _installed_chrome,
    _load_chrome_artifact,
    _preconfigure_google_repo_opt_out,
    _repo_opt_out_is_false,
    _verify_deb_metadata,
)
root = Path(sys.argv[1])
package_path, artifact = _load_chrome_artifact(root)
_verify_deb_metadata(package_path, artifact)
if _installed_chrome() is not None:
    raise SystemExit("chrome_present_before_fresh_install_gate")
before_sources = sorted(str(path) for path in _active_google_repo_files())
if before_sources:
    raise SystemExit("active_google_repo_before_fresh_install_gate:" + ",".join(before_sources))
_preconfigure_google_repo_opt_out()
if not _repo_opt_out_is_false():
    raise SystemExit("chrome_repo_opt_out_not_established")
_ensure_exact_chrome(package_path, artifact)
installed = _installed_chrome()
if installed is None:
    raise SystemExit("chrome_missing_after_fresh_install_gate")
if installed[1] != str(artifact["version"]) or installed[2] != str(artifact["architecture"]):
    raise SystemExit("chrome_identity_mismatch_after_fresh_install_gate")
after_sources = sorted(str(path) for path in _active_google_repo_files())
if after_sources:
    raise SystemExit("chrome_install_added_active_repo:" + ",".join(after_sources))
print(
    "CLIENTFLOW_DISPLAY_PLATFORM_INSTALL_OK "
    + json.dumps(
        {
            "architecture": installed[2],
            "package": "google-chrome-stable",
            "version": installed[1],
        },
        sort_keys=True,
    )
)
'''
    result = subprocess.run(
        [str(runtime_python), "-I", "-c", code, str(release_root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
        check=False,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    marker = "CLIENTFLOW_DISPLAY_PLATFORM_INSTALL_OK "
    if result.returncode != 0 or marker not in result.stdout:
        raise CandidateGateError(
            "Exact embedded Display platform-artifact kunne ikke installeres på target host:\n"
            + result.stdout[-8000:]
        )
    payload = result.stdout.rsplit(marker, 1)[1].splitlines()[0]
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CandidateGateError("Display platform-install gate gav ugyldig success-payload") from exc
    return {
        "package": str(parsed.get("package") or ""),
        "version": str(parsed.get("version") or ""),
        "architecture": str(parsed.get("architecture") or ""),
    }


def verify_display_platform_install_candidate(candidate_dir: Path) -> dict[str, object]:
    candidate = _exact_one(candidate_dir, "*-candidate.tar")
    manifest, payload, _bundle_size, candidate_sha256, handle = open_verified_bundle(
        candidate,
        require_deployable=False,
    )
    try:
        if manifest.get("deployable") is not False:
            raise CandidateGateError("Release-build candidate må aldrig være deployable")
        validate_runtime_artifacts(payload, manifest)
        with tempfile.TemporaryDirectory(prefix="clientflow-display-install-gate-") as temp_dir:
            workspace = Path(temp_dir)
            extracted = extract_verified_payload(
                payload,
                workspace / "payload",
                expected_root=manifest["payload"]["root"],
            )
            prepare_runtime(extracted, manifest)
            _validate_prepared_release_tree(extracted, manifest)
            _verify_embedded_display_platform_artifact(extracted)
            installed = _verify_display_platform_install_on_host(extracted)
    finally:
        handle.close()

    return {
        "status": "candidate_display_platform_install_gate_pass",
        "candidate": candidate.name,
        "candidate_sha256": candidate_sha256,
        "release_id": manifest["release_id"],
        "version": manifest["version"],
        "release_sequence": manifest["release_sequence"],
        "display_platform_install": installed,
    }


def _managed_units_synthetic_root(release_root: Path, manifest: dict, workspace: Path) -> tuple[Path, list[Path]]:
    layout = Layout(workspace / "managed-root")
    unit_names = _apply_definitions(
        layout,
        release_root,
        kiosk_user="ci-kiosk",
        client_id=424242,
    )
    if not unit_names:
        raise CandidateGateError("Managed definition materialization gav ingen units")
    for name in unit_names:
        text = (layout.unit_root / name).read_text(encoding="utf-8")
        if re.search(r"@[A-Z0-9_]+@", text):
            raise CandidateGateError(f"Managed unit har uløst placeholder: {name}")

    root = workspace / "systemd-root"
    unit_root = root / "etc/systemd/system"
    unit_root.mkdir(parents=True)
    for name in unit_names:
        shutil.copy2(layout.unit_root / name, unit_root / name)

    # systemd-analyze --root only needs executable/path presence for Exec*=.
    # Actual candidate bytes were already validated above by systemd_contract.
    active = root / "opt/clientflow/active"
    active.parent.mkdir(parents=True, exist_ok=True)
    (root / "opt/clientflow/releases/ci").mkdir(parents=True)
    active.symlink_to("releases/ci")

    release_units = release_root / "client-runtime/systemd"
    for unit in release_units.glob("*.service"):
        for raw in unit.read_text(encoding="utf-8").splitlines():
            if not raw.startswith(("ExecStart=", "ExecStartPre=", "ExecStartPost=", "ExecStop=", "ExecStopPost=", "ExecReload=", "ExecCondition=")):
                continue
            value = raw.split("=", 1)[1].lstrip("-+!:@|").strip()
            try:
                tokens = __import__("shlex").split(value)
            except ValueError as exc:
                raise CandidateGateError(f"Ugyldig Exec directive i {unit.name}") from exc
            for token_index, token in enumerate(tokens):
                if token.startswith("/opt/clientflow/active/"):
                    target = root / token.lstrip("/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    # Direct commands must be executable; interpreter-owned scripts
                    # may also be executable in the synthetic root without weakening
                    # the actual candidate-mode validation performed earlier.
                    target.chmod(0o755)
                elif token_index == 0 and token in {"/bin/sh", "/usr/bin/python3"}:
                    target = root / token.lstrip("/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    target.chmod(0o755)
                elif token == "/usr/lib/clientflow/updater/clientflow-updater.pyz":
                    target = root / token.lstrip("/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("candidate-updater-placeholder\n", encoding="utf-8")

    return root, [unit_root / name for name in unit_names]


def _systemd_verify(release_root: Path, manifest: dict, workspace: Path) -> None:
    systemd_analyze = shutil.which("systemd-analyze")
    if not systemd_analyze:
        raise CandidateGateError("Target host mangler systemd-analyze")
    root, units = _managed_units_synthetic_root(release_root, manifest, workspace)
    result = subprocess.run(
        [
            systemd_analyze,
            f"--root={root}",
            "--recursive-errors=no",
            "--man=no",
            "verify",
            *map(str, units),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise CandidateGateError("systemd-analyze verify fejlede:\n" + result.stdout[-12000:])


def verify_candidate(candidate_dir: Path, repo: Path, system_python: Path) -> dict[str, object]:
    candidate = _exact_one(candidate_dir, "*-candidate.tar")
    installer = _exact_one(candidate_dir, "clientflow-installer-*.pyz")
    manifest, payload, _bundle_size, candidate_sha256, handle = open_verified_bundle(
        candidate,
        require_deployable=False,
    )
    try:
        validate_runtime_artifacts(payload, manifest)
        _verify_source_identity(repo, manifest)
        _verify_installer_on_host(installer, manifest, system_python)
        with tempfile.TemporaryDirectory(prefix="clientflow-candidate-gate-") as temp_dir:
            workspace = Path(temp_dir)
            extracted = extract_verified_payload(payload, workspace / "payload", expected_root=manifest["payload"]["root"])
            prepare_runtime(extracted, manifest)
            _validate_prepared_release_tree(extracted, manifest)
            _verify_embedded_display_platform_artifact(extracted)
            summary = validate_release_systemd_contract(extracted)
            _systemd_verify(extracted, manifest, workspace)
            release_ready = json.loads((extracted / "release-ready.json").read_text(encoding="utf-8"))
    finally:
        handle.close()

    return {
        "status": "candidate_operational_gate_pass",
        "candidate": candidate.name,
        "candidate_sha256": candidate_sha256,
        "release_id": manifest["release_id"],
        "version": manifest["version"],
        "release_sequence": manifest["release_sequence"],
        "host_python": platform.python_version(),
        "prepared_runtime_python": release_ready["python"],
        "systemd_unit_count": summary["unit_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--system-python", type=Path, default=Path("/usr/bin/python3"))
    parser.add_argument("--display-platform-install-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.display_platform_install_only:
            result = verify_display_platform_install_candidate(args.candidate_dir.resolve())
        else:
            result = verify_candidate(args.candidate_dir.resolve(), args.repo.resolve(), args.system_python)
    except Exception as exc:
        print(f"CLIENTFLOW_CANDIDATE_OPERATIONAL_GATE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
