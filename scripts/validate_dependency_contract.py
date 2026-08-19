#!/usr/bin/env python3
"""Validate PlanIQ Display runtime pins and dependency locks without network access."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "PlanIQ Display"
KIND = "display"
PYTHON_VERSION = "3.13.14"
NODE_VERSION = "22.22.0"
NPM_VERSION = "10.9.4"
PIP_VERSION = "26.1.2"
DIRECT_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;]+)$")
LOCK_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)(?:\s+\\)?$")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_direct(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = DIRECT_RE.fullmatch(line)
        if not match:
            raise ValueError(f"{path.relative_to(ROOT)}:{number} skal være eksakt name==version: {line}")
        name, version = match.groups()
        result[normalize(name)] = version
    if not result:
        raise ValueError(f"{path.relative_to(ROOT)} er tom")
    return result


def read_hashed_lock(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if "packages.applied-caas" in text or "reader:" in text:
        raise ValueError(f"{path.relative_to(ROOT)} må ikke indeholde interne index-oplysninger")
    lines = text.splitlines()
    result: dict[str, str] = {}
    current: str | None = None
    hashes = 0
    for raw in lines + [""]:
        if raw and not raw[0].isspace() and not raw.startswith("#"):
            if current is not None and hashes == 0:
                raise ValueError(f"{path.relative_to(ROOT)} mangler hash for {current}")
            match = LOCK_RE.fullmatch(raw.strip())
            if not match:
                raise ValueError(f"Ugyldig locklinje i {path.relative_to(ROOT)}: {raw}")
            name, version = match.groups()
            current = normalize(name)
            result[current] = version
            hashes = 0
        elif "--hash=sha256:" in raw:
            hashes += 1
    if current is not None and hashes == 0:
        raise ValueError(f"{path.relative_to(ROOT)} mangler hash for {current}")
    if not result:
        raise ValueError(f"{path.relative_to(ROOT)} er tom")
    return result


def require_subset(source: dict[str, str], lock: dict[str, str], label: str) -> None:
    for name, version in source.items():
        if lock.get(name) != version:
            raise ValueError(f"{label}: {name}=={version} mangler eller afviger")


def check_flow_vendor(package: dict) -> None:
    if package.get("dependencies", {}).get("xlsx") != "file:vendor/xlsx-0.20.3.tgz":
        raise ValueError("Flow skal bruge den vendorede SheetJS 0.20.3-tarball")
    vendor = ROOT / "frontend/vendor/xlsx-0.20.3.tgz"
    if not vendor.is_file():
        raise ValueError("Flow mangler frontend/vendor/xlsx-0.20.3.tgz")
    expected = "28752d85a25ec8d418665e8401373f4bf52816412cd01fd39f39e1c4a7042020"
    actual = hashlib.sha256(vendor.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("Flow SheetJS-tarballens SHA-256 afviger")
    with tarfile.open(vendor, "r:gz") as archive:
        metadata = json.load(archive.extractfile("package/package.json"))
    if metadata.get("version") != "0.20.3":
        raise ValueError("Flow SheetJS-tarball skal være version 0.20.3")


def check_worklog_overrides(package: dict) -> None:
    expected = {"form-data": "4.0.6", "tmp": "0.2.7", "uuid": "11.1.1"}
    if package.get("overrides") != expected:
        raise ValueError(f"Worklog overrides afviger: forventet {expected}")


def main() -> int:
    required = [
        "backend/.python-version", "backend/requirements.txt", "backend/requirements.lock.txt",
        "requirements-ci.txt", "requirements-ci.lock.txt", "frontend/.node-version", "frontend/package.json",
        "frontend/package-lock.json", "frontend/dependency-audit-allowlist.json",
        "frontend/scripts/auditDependencies.mjs", "frontend/tests/dependencyRuntime.test.mjs",
        "DEPENDENCY_MAINTENANCE.md", ".github/workflows/ci.yml", "render.yaml",
    ]
    missing = [item for item in required if not (ROOT / item).is_file()]
    if missing:
        raise ValueError(f"Manglende dependency-kontraktfiler: {missing}")
    if (ROOT / "backend/.python-version").read_text().strip() != PYTHON_VERSION:
        raise ValueError("backend/.python-version afviger")
    if (ROOT / "frontend/.node-version").read_text().strip() != NODE_VERSION:
        raise ValueError("frontend/.node-version afviger")

    production = read_direct(ROOT / "backend/requirements.txt")
    production_lock = read_hashed_lock(ROOT / "backend/requirements.lock.txt")
    ci = read_direct(ROOT / "requirements-ci.txt")
    ci_lock = read_hashed_lock(ROOT / "requirements-ci.lock.txt")
    require_subset(production, production_lock, "Production lock")
    require_subset(production, ci_lock, "CI lock")
    require_subset(ci, ci_lock, "CI lock")

    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    if lock.get("lockfileVersion") != 3:
        raise ValueError("frontend/package-lock.json skal bruge lockfileVersion 3")
    lock_root = (lock.get("packages") or {}).get("")
    if not isinstance(lock_root, dict):
        raise ValueError("package-lock mangler packages['']")
    if package.get("engines") != {"node": NODE_VERSION, "npm": NPM_VERSION}:
        raise ValueError("Frontend engines afviger")
    if package.get("packageManager") != f"npm@{NPM_VERSION}":
        raise ValueError("Frontend packageManager afviger")
    for key in ("name", "version", "dependencies", "devDependencies", "engines"):
        if package.get(key, {}) != lock_root.get(key, {}):
            raise ValueError(f"package.json og package-lock afviger for {key}")
    for name, value in {
        "audit:dependencies": "node scripts/auditDependencies.mjs",
        "test:dependency-runtime": "node --test tests/dependencyRuntime.test.mjs",
    }.items():
        if package.get("scripts", {}).get(name) != value:
            raise ValueError(f"Frontend script {name} mangler eller afviger")
    expected_dev = {
        "@eslint/js": "9.39.5",
        "eslint": "9.39.5",
        "eslint-plugin-react-hooks": "7.1.1",
        "globals": "15.14.0",
        "@vitejs/plugin-react": "6.0.3",
        "vite": "8.1.4",
    }
    packages = lock.get("packages") or {}
    for name, version in expected_dev.items():
        if package.get("devDependencies", {}).get(name) != version:
            raise ValueError(f"{name} skal være fastlåst til {version}")
        if packages.get(f"node_modules/{name}", {}).get("version") != version:
            raise ValueError(f"package-lock resolver ikke {name} til {version}")
    if KIND == "flow":
        check_flow_vendor(package)
    if KIND == "worklog":
        check_worklog_overrides(package)

    audit_script = (ROOT / "frontend/scripts/auditDependencies.mjs").read_text(encoding="utf-8")
    if 'spawnSync("npm", ["audit", "--json"]' not in audit_script:
        raise ValueError("Frontend dependency-audit skal bruge npm audit --json")
    allowlist = json.loads((ROOT / "frontend/dependency-audit-allowlist.json").read_text())
    for entry in allowlist.get("exceptions", []):
        for field in ("package", "advisories", "expires", "scope", "replacementPlan"):
            if not entry.get(field):
                raise ValueError(f"Dependency-undtagelse mangler {field}")
        if date.fromisoformat(entry["expires"]) < date.today():
            raise ValueError(f"Dependency-undtagelse er udløbet: {entry['package']}")

    render = yaml.safe_load((ROOT / "render.yaml").read_text()) or {}
    services = render.get("services", [])
    web = next((item for item in services if item.get("type") == "web"), None)
    static = next((item for item in services if item.get("type") == "static"), None)
    if not web or not static:
        raise ValueError("render.yaml mangler web/static service")
    build = str(web.get("buildCommand"))
    for token in (f"pip=={PIP_VERSION}", "--require-hashes", "requirements.lock.txt"):
        if token not in build:
            raise ValueError(f"Render backend-build mangler {token}")
    if str(static.get("buildCommand")) != "npm ci && npm run build":
        raise ValueError("Render frontend-build skal være præcis npm ci && npm run build")
    web_env = {item.get("key"): item.get("value") for item in web.get("envVars", [])}
    static_env = {item.get("key"): item.get("value") for item in static.get("envVars", [])}
    if web_env.get("PYTHON_VERSION") != PYTHON_VERSION:
        raise ValueError("Render PYTHON_VERSION afviger")
    if static_env.get("NODE_VERSION") != NODE_VERSION:
        raise ValueError("Render NODE_VERSION afviger")

    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    for token in (
        f'python-version: "{PYTHON_VERSION}"', f'node-version: "{NODE_VERSION}"',
        f'test "$(npm --version)" = "{NPM_VERSION}"', "--require-hashes -r requirements-ci.lock.txt",
        "python -m pip_audit --disable-pip --no-deps --progress-spinner off -r backend/requirements.lock.txt",
        "python scripts/validate_dependency_contract.py",
        "python -m ruff check backend/service1 backend/scripts scripts --select F",
        "npm run audit:dependencies",
        "npm run test:dependency-runtime",
        "npm run test:mui-react-upgrade",
        "npm run test:snackbar-contract",
    ):
        if token not in workflow:
            raise ValueError(f"CI dependency-kontrakt mangler: {token}")

    print(f"Dependency-kontrakt bestået: {PRODUCT}, Python {PYTHON_VERSION}, Node {NODE_VERSION}, npm {NPM_VERSION}, pip {PIP_VERSION}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError, tarfile.TarError) as exc:
        print(f"Dependency-kontrakt fejlede: {exc}", file=sys.stderr)
        raise SystemExit(1)
