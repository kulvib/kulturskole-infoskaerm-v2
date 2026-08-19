from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("PASSWORD_RESET_FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")
os.environ.setdefault("HLS_BASE_DIR", "/tmp/planiq-display-ci-hls")

from service1.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]


class BackendCleanupContractTests(unittest.TestCase):
    def test_retired_client_placeholder_and_duplicate_hls_routes_are_absent(self) -> None:
        route_paths = set()
        for route in app.routes:
            path = getattr(route, "path", None)
            if path:
                route_paths.add(path)
                continue
            original_router = getattr(route, "original_router", None)
            include_context = getattr(route, "include_context", None)
            prefix = getattr(include_context, "prefix", "") if include_context else ""
            for nested in getattr(original_router, "routes", []):
                nested_path = getattr(nested, "path", None)
                if nested_path:
                    route_paths.add(f"{prefix}{nested_path}")

        self.assertIn("/api/hls/{client_id}/reset", route_paths)

        retired = {
            "/api/clients/{id}/stream",
            "/api/clients/{id}/terminal",
            "/api/clients/{id}/remote-desktop",
            "/api/clients/{client_id}/reset-hls",
            "/api/clients/{client_id}/stop-hls",
        }
        self.assertTrue(retired.isdisjoint(route_paths), retired & route_paths)

    def test_frontend_uses_only_canonical_hls_reset_and_no_dead_api_exports(self) -> None:
        api_source = (REPO_ROOT / "frontend/src/api/api.js").read_text(encoding="utf-8")
        livestream_source = (
            REPO_ROOT / "frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx"
        ).read_text(encoding="utf-8")

        self.assertNotIn("export function openTerminal", api_source)
        self.assertNotIn("export function getClientStream", api_source)
        self.assertNotIn("/reset-hls", livestream_source)
        self.assertIn("/api/hls/${encodeURIComponent(clientId)}/reset", livestream_source)

    def test_enrollment_claim_locks_active_tokens_against_concurrent_reuse(self) -> None:
        enrollment_source = (
            REPO_ROOT / "backend/service1/routers/enrollment.py"
        ).read_text(encoding="utf-8")
        self.assertIn(".with_for_update()", enrollment_source)
        self.assertLess(
            enrollment_source.index(".with_for_update()"),
            enrollment_source.index("token.used_at = now"),
        )

    def test_ci_checks_the_complete_ruff_f_family_with_only_frozen_livestream_exemptions(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        dependency_validator = (REPO_ROOT / "scripts/validate_dependency_contract.py").read_text(encoding="utf-8")
        ruff_config = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")

        required = "python -m ruff check backend/service1 backend/scripts scripts --select F"
        for source in (workflow, dependency_validator):
            self.assertIn(required, source)
            self.assertNotIn("--select F821,F822,F823", source)
            self.assertNotIn("--ignore F401", source)

        self.assertIn('"backend/service1/livestream_v2.py" = ["F401"]', ruff_config)
        self.assertIn('"backend/service1/routers/livestream_v2.py" = ["F401"]', ruff_config)
        self.assertNotIn('ignore = ["F401"]', ruff_config)


if __name__ == "__main__":
    unittest.main()
