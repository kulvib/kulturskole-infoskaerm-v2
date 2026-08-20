from __future__ import annotations

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
FULL_SHA_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


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
    for workflow in ("ci.yml", "deployment-smoke.yml", "release-build.yml"):
        source, _ = _load(workflow)
        actions = _external_actions(source)
        assert actions
        assert all(FULL_SHA_ACTION_RE.fullmatch(action) for action in actions)
        assert "persist-credentials: false" in source


def test_ci_uses_read_only_permissions_and_safe_triggers():
    source, workflow = _load("ci.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
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
