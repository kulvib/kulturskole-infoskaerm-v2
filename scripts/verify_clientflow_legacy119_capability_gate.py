#!/usr/bin/env python3
"""Executable legacy 1.1.19 functional-capability gate for ClientFlow V2.

The immutable legacy installer is not copied into V2.  Instead this gate pins its
installer/payload identities and the exact 177-file installer+payload inventory,
then binds every accepted legacy capability to current V2 replacements and to
real CI proofs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "client/legacy-client-parity.json"
CI_WORKFLOW = REPO / ".github/workflows/ci.yml"

EXPECTED_BASELINE = {
    "release": "1.1.19",
    "sequence": 1119,
    "installer_zip_sha256": "61dc8a417aaa32f4eabc7430a2af886933473142cebcdcbe8f1064a318941e80",
    "installer_zip_size": 528568,
    "payload_tar_sha256": "d490dd8f0effccc58e8d5687ae95d0821bf2747d4f131a2ee3a9c3088c1ec331",
    "payload_tar_size": 482779,
    "payload_file_count": 166,
    "installer_surface_file_count": 11,
    "total_inventory_count": 177,
    "inventory_sha256": "e542df2c1c3d9b6c4a88966803bb6f39c6a938744756e6202eb9abde83a8d695",
}
ALLOWED_STATUSES = {"implemented", "architecturally_replaced", "obsolete"}
PROOF_CLASSES = {"integration", "host", "behavior", "source_contract"}
EXECUTABLE_PROOF_CLASSES = {"integration", "host", "behavior"}
REQUIRED_CAPABILITIES = {
    "fresh_install_factory_enrollment",
    "human_accounts_desktop_session",
    "network_identity_bootstrap",
    "display_browser_calendar",
    "local_gui_support",
    "time_session_popup",
    "local_power_system_os_update",
    "release_update_recovery",
    "status_diagnostics",
    "frozen_livestream",
    "frozen_terminal",
    "frozen_remote_desktop",
    "state_config_dependency_materialization",
}
FROZEN_CAPABILITIES = {"frozen_livestream", "frozen_terminal", "frozen_remote_desktop"}


class GateError(RuntimeError):
    pass


def _load(repo: Path) -> dict:
    path = repo / MANIFEST.relative_to(REPO)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"Kan ikke læse legacy parity manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise GateError("Legacy parity manifest skal være et JSON object")
    return payload


def _inventory_digest(rows: list[dict]) -> str:
    lines = []
    for row in sorted(rows, key=lambda item: (item["surface"], item["path"])):
        lines.append(
            f'{row["surface"]}\t{row["path"]}\t{row["size"]}\t{row["sha256"]}\t{row["primary_capability"]}'
        )
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def _validate(repo: Path) -> dict[str, object]:
    payload = _load(repo)
    if payload.get("schema_version") != 2:
        raise GateError("legacy-client-parity.json skal bruge schema_version 2")
    if payload.get("legacy_baseline") != EXPECTED_BASELINE:
        raise GateError("Legacy 1.1.19 immutable baseline identity/inventory er driftet")
    if set(payload.get("allowed_statuses") or []) != ALLOWED_STATUSES:
        raise GateError("allowed_statuses er driftet")
    if set(payload.get("proof_classes") or []) != PROOF_CLASSES:
        raise GateError("proof_classes er driftet")

    capabilities = payload.get("capabilities")
    inventory = payload.get("inventory")
    if not isinstance(capabilities, list) or not isinstance(inventory, list):
        raise GateError("capabilities og inventory skal være arrays")

    by_id: dict[str, dict] = {}
    for cap in capabilities:
        cap_id = str(cap.get("id") or "")
        if not cap_id or cap_id in by_id:
            raise GateError(f"Ugyldigt/duplikeret capability id: {cap_id!r}")
        by_id[cap_id] = cap
    if set(by_id) != REQUIRED_CAPABILITIES:
        raise GateError(
            "Capability matrix er driftet: "
            f"missing={sorted(REQUIRED_CAPABILITIES - set(by_id))} "
            f"extra={sorted(set(by_id) - REQUIRED_CAPABILITIES)}"
        )
    frozen = {cap_id for cap_id, cap in by_id.items() if cap.get("frozen") is True}
    if frozen != FROZEN_CAPABILITIES:
        raise GateError(f"Frozen capability-set er driftet: {sorted(frozen)}")

    inventory_keys: set[str] = set()
    payload_count = 0
    installer_count = 0
    for row in inventory:
        surface = row.get("surface")
        path = str(row.get("path") or "")
        key = f"{surface}:{path}"
        if surface not in {"payload", "installer"}:
            raise GateError(f"Ugyldig inventory surface: {surface!r}")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise GateError(f"Ugyldig legacy inventory path: {path!r}")
        if key in inventory_keys:
            raise GateError(f"Duplikeret legacy inventory entry: {key}")
        inventory_keys.add(key)
        if surface == "payload":
            payload_count += 1
        else:
            installer_count += 1
        size = row.get("size")
        digest = str(row.get("sha256") or "")
        if not isinstance(size, int) or size < 0:
            raise GateError(f"Ugyldig size for {key}")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise GateError(f"Ugyldig SHA256 for {key}")
        primary = str(row.get("primary_capability") or "")
        if primary not in by_id:
            raise GateError(f"Inventory entry {key} har ukendt capability {primary!r}")

    if payload_count != EXPECTED_BASELINE["payload_file_count"]:
        raise GateError(f"Legacy payload inventory skal have 166 filer, fik {payload_count}")
    if installer_count != EXPECTED_BASELINE["installer_surface_file_count"]:
        raise GateError(f"Legacy installer surface skal have 11 filer, fik {installer_count}")
    if len(inventory) != EXPECTED_BASELINE["total_inventory_count"]:
        raise GateError(f"Legacy total inventory skal have 177 entries, fik {len(inventory)}")
    if _inventory_digest(inventory) != EXPECTED_BASELINE["inventory_sha256"]:
        raise GateError("Legacy 1.1.19 exact inventory digest er driftet")

    workflow = (repo / CI_WORKFLOW.relative_to(REPO)).read_text(encoding="utf-8")
    executable_capabilities = 0
    proof_files: dict[str, set[str]] = {"python": set(), "frontend": set(), "host": set()}
    for cap_id, cap in by_id.items():
        if cap.get("status") not in ALLOWED_STATUSES:
            raise GateError(f"{cap_id}: ugyldig status")
        if not str(cap.get("rationale") or "").strip():
            raise GateError(f"{cap_id}: rationale mangler")
        evidence = cap.get("legacy_evidence") or []
        if not evidence:
            raise GateError(f"{cap_id}: legacy_evidence mangler")
        for key in evidence:
            if key not in inventory_keys:
                raise GateError(f"{cap_id}: ukendt legacy evidence {key}")
        replacements = cap.get("v2_replacements") or []
        if not replacements:
            raise GateError(f"{cap_id}: V2 replacement mangler")
        for rel in replacements:
            if not (repo / rel).exists():
                raise GateError(f"{cap_id}: V2 replacement findes ikke: {rel}")

        proofs = cap.get("proofs") or []
        if not proofs:
            raise GateError(f"{cap_id}: proof-set mangler")
        has_executable = False
        for proof in proofs:
            scope = proof.get("scope")
            path = str(proof.get("path") or "")
            proof_class = proof.get("proof_class")
            execution = proof.get("execution", "gate")
            if scope not in proof_files:
                raise GateError(f"{cap_id}: ukendt proof scope {scope!r}")
            if proof_class not in PROOF_CLASSES:
                raise GateError(f"{cap_id}: ukendt proof_class {proof_class!r}")
            if not (repo / path).is_file():
                raise GateError(f"{cap_id}: proof fil findes ikke: {path}")
            proof_files[scope].add(path)
            if proof_class in EXECUTABLE_PROOF_CLASSES:
                has_executable = True
            if execution == "ci_external" and path not in workflow:
                raise GateError(f"{cap_id}: external CI proof er ikke wired i ci.yml: {path}")
            if execution not in {"gate", "ci_external"}:
                raise GateError(f"{cap_id}: ukendt execution {execution!r}")
        if not has_executable:
            raise GateError(f"{cap_id}: capability har kun source-contract proofs")
        executable_capabilities += 1

    return {
        "legacy_release": EXPECTED_BASELINE["release"],
        "payload_files": payload_count,
        "installer_files": installer_count,
        "inventory_entries": len(inventory),
        "capabilities": len(by_id),
        "capabilities_with_executable_proof": executable_capabilities,
        "python_proof_files": len(proof_files["python"]),
        "frontend_proof_files": len(proof_files["frontend"]),
        "host_proof_files": len(proof_files["host"]),
    }


def _gate_paths(repo: Path, scope: str) -> list[str]:
    payload = _load(repo)
    paths: set[str] = set()
    for cap in payload["capabilities"]:
        for proof in cap.get("proofs") or []:
            if proof.get("scope") == scope and proof.get("execution", "gate") == "gate":
                paths.add(str(proof["path"]))
    return sorted(paths)


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 300) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        raise GateError(f"Executable parity proof fejlede ({result.returncode}): {' '.join(command)}")


def _execute_python(repo: Path) -> None:
    paths = _gate_paths(repo, "python")
    if not paths:
        raise GateError("Ingen Python proof files i capability-gaten")
    _run([sys.executable, "-m", "pytest", "-q", *paths], cwd=repo, env=dict(os.environ), timeout=600)


def _execute_frontend(repo: Path) -> None:
    node = shutil.which("node")
    if not node:
        raise GateError("node mangler til frontend parity gate")
    paths = _gate_paths(repo, "frontend")
    if not paths:
        raise GateError("Ingen frontend proof files i capability-gaten")
    relative = [str(Path(path).relative_to("frontend")) for path in paths]
    _run([node, "--test", *relative], cwd=repo / "frontend", env=dict(os.environ), timeout=300)


def _execute_host(repo: Path) -> None:
    os_release = {}
    for raw in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            os_release[key] = value.strip().strip('"')
    if (os_release.get("ID"), os_release.get("VERSION_ID")) != ("ubuntu", "26.04"):
        raise GateError("Host parity gate kræver exact Ubuntu 26.04")
    for binary in ("/usr/bin/apt-get", "/usr/bin/curl", "/usr/bin/timedatectl", "/usr/bin/systemctl"):
        if not Path(binary).is_file():
            raise GateError(f"Host parity capability mangler efter host bootstrap: {binary}")
    paths = _gate_paths(repo, "host")
    for path in paths:
        if path.endswith("verify_clientflow_ubuntu2604_host.py"):
            _run(["/usr/bin/python3", path, "--repo", str(repo)], cwd=repo, env=dict(os.environ), timeout=180)
        else:
            raise GateError(f"Host proof mangler eksplicit executable dispatch: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--scope", choices=("validate", "python", "frontend", "host"), default="validate")
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        summary = _validate(repo)
        if args.scope == "python":
            _execute_python(repo)
        elif args.scope == "frontend":
            _execute_frontend(repo)
        elif args.scope == "host":
            _execute_host(repo)
    except (GateError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"clientflow-legacy119-capability-gate: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "scope": args.scope, **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
