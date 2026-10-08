from __future__ import annotations

from pathlib import Path
import json
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
FULL_SHA_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
PINNED_POSTGRES_IMAGE = "postgres:18.4@sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280"


def _load(name: str) -> tuple[str, dict]:
    path = WORKFLOW_DIR / name
    source = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(source)
    assert isinstance(parsed, dict)
    return source, parsed


def _external_actions(source: str) -> list[str]:
    actions: list[str] = []
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("uses:"):
            continue
        value = stripped.split(":", 1)[1].strip().split(" #", 1)[0]
        if value.startswith("./"):
            continue
        actions.append(value)
    return actions


def test_external_actions_are_immutable_and_checkout_drops_credentials():
    for workflow in (
        "ci.yml",
        "deployment-smoke.yml",
        "release-build.yml",
        "dependency-maintenance-candidate.yml",
    ):
        source, _ = _load(workflow)
        actions = _external_actions(source)
        assert actions
        assert all(FULL_SHA_ACTION_RE.fullmatch(action) for action in actions)
        assert "persist-credentials: false" in source



def test_workflow_execution_environment_is_immutable():
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        source = path.read_text(encoding="utf-8")
        assert "runs-on: ubuntu-latest" not in source, path.name

        for raw_line in source.splitlines():
            stripped = raw_line.strip()
            if not stripped.startswith("image: postgres:"):
                continue
            image = stripped.split(":", 1)[1].strip()
            assert image == PINNED_POSTGRES_IMAGE, path.name

def test_ci_uses_read_only_permissions_and_safe_triggers():
    source, workflow = _load("ci.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["on"]["push"] == {"branches": ["main"]}
    assert workflow["on"]["pull_request"] == {"branches": ["main"]}
    assert "pull_request_target" not in source
    assert "secrets." not in source


def test_production_smoke_is_manual_main_only_and_uses_dispatched_sha():
    source, workflow = _load("deployment-smoke.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert 'test "$GITHUB_REF" = "refs/heads/main"' in source
    assert "EXPECTED_COMMIT: ${{ github.sha }}" in source
    assert "python scripts/check_production_readiness.py" in source
    assert "secrets." not in source

def test_dependency_maintenance_candidate_keeps_pyjwt_security_floor():
    source, _ = _load("dependency-maintenance-candidate.yml")
    assert 'text.count("PyJWT==2.15.1") != 1' in source
    assert '"security_floor": {"PyJWT": "2.15.1"}' in source

def test_backend_ci_does_not_duplicate_dedicated_python_gates():
    source, _ = _load("ci.yml")
    manifest = json.loads((ROOT / "client/legacy-client-parity.json").read_text(encoding="utf-8"))

    broad_start = source.index("- name: Run Python test suite")
    operational_start = source.index("- name: Execute ClientFlow synthetic end-to-end operational gate")
    legacy_start = source.index("- name: Execute legacy 1.1.19 capability parity gate")
    host_start = source.index("  client-host-ubuntu-2604:")

    broad = source[broad_start:operational_start]
    operational = source[operational_start:legacy_start]
    legacy = source[legacy_start:host_start]

    path_re = re.compile(r"(?:backend|scripts)/tests/[A-Za-z0-9_./-]+\.py")
    ignored = {item.removeprefix("--ignore=") for item in re.findall(r"--ignore=((?:backend|scripts)/tests/[A-Za-z0-9_./-]+\.py)", broad)}
    operational_paths = set(path_re.findall(operational))
    legacy_paths = {
        proof["path"]
        for capability in manifest["capabilities"]
        for proof in capability.get("proofs", [])
        if proof.get("scope") == "python" and proof.get("execution", "gate") == "gate"
    }

    assert operational_paths
    assert legacy_paths
    assert not (operational_paths & legacy_paths)
    assert ignored == operational_paths | legacy_paths
    assert "python -m pytest -q" in broad
    assert "backend/tests scripts/tests" in broad
    assert "--scope python" in legacy


def test_backend_ci_uses_fast_postgres_health_probe_and_hash_lock_cache():
    source, _ = _load("ci.yml")
    assert '--health-interval 1s' in source
    assert '--health-interval 10s' not in source
    assert 'cache: "pip"' in source
    assert 'cache-dependency-path: requirements-ci.lock.txt' in source

def test_ubuntu_2604_required_gate_parallelizes_and_scopes_expensive_executable_proofs():
    source, workflow = _load("ci.yml")
    jobs = workflow["jobs"]

    scope = jobs["client-host-ubuntu-2604-scope"]
    required = jobs["client-host-ubuntu-2604"]
    preclaim = jobs["client-host-ubuntu-2604-preclaim"]
    platform = jobs["client-host-ubuntu-2604-platform"]

    assert scope["name"] == "Ubuntu 26.04 executable proof scope"
    assert scope["runs-on"] == "ubuntu-24.04"
    assert set(scope["outputs"]) == {"preclaim_required", "platform_required"}

    assert required["name"] == "Ubuntu 26.04 client host executable contracts"
    assert set(required["needs"]) == {
        "client-host-ubuntu-2604-scope",
        "client-host-ubuntu-2604-preclaim",
        "client-host-ubuntu-2604-platform",
    }
    assert required["if"] == "${{ always() }}"
    assert required["runs-on"] == "ubuntu-24.04"

    assert preclaim["needs"] == "client-host-ubuntu-2604-scope"
    assert preclaim["if"] == "${{ needs.client-host-ubuntu-2604-scope.outputs.preclaim_required == 'true' }}"
    assert preclaim["runs-on"] == "ubuntu-26.04"

    assert platform["needs"] == "client-host-ubuntu-2604-scope"
    assert platform["if"] == "${{ needs.client-host-ubuntu-2604-scope.outputs.platform_required == 'true' }}"
    assert platform["runs-on"] == "ubuntu-26.04"

    scope_source = source[
        source.index("  client-host-ubuntu-2604-scope:"):
        source.index("  client-host-ubuntu-2604:")
    ]
    assert 'if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ]' in scope_source
    assert "client/release/runtime-platform-inputs.lock.json" in scope_source
    assert "client/release/lib/clientflow_release/*" in scope_source
    assert "client/*" in scope_source
    assert "backend/clientflow_release_format/*" in scope_source

    required_source = source[
        source.index("  client-host-ubuntu-2604:"):
        source.index("  client-host-ubuntu-2604-preclaim:")
    ]
    assert 'test "$SCOPE_RESULT" = "success"' in required_source
    assert 'test "$PRECLAIM_RESULT" = "skipped"' in required_source
    assert 'test "$PLATFORM_RESULT" = "skipped"' in required_source

    preclaim_source = source[
        source.index("  client-host-ubuntu-2604-preclaim:"):
        source.index("  client-host-ubuntu-2604-platform:")
    ]
    platform_source = source[
        source.index("  client-host-ubuntu-2604-platform:"):
        source.index("  frontend:")
    ]
    assert "verify_clientflow_preclaim_bootstrap_ubuntu2604.py" in preclaim_source
    assert "--install-platform-requirements" not in preclaim_source
    assert "verify_clientflow_ubuntu2604_host.py" in platform_source
    assert "--install-platform-requirements" in platform_source
    assert "--scope host" in platform_source

