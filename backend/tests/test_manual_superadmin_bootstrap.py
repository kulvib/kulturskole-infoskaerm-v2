from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManualSuperadminBootstrapContractTests(unittest.TestCase):
    def test_application_startup_never_creates_users(self) -> None:
        source = (ROOT / "service1/main.py").read_text(encoding="utf-8")
        self.assertNotIn("ensure_admin_user", source)
        self.assertNotIn("ADMIN_PASSWORD", source)
        self.assertNotIn("startup_superadmin_created", source)

    def test_recovery_command_requires_explicit_confirmation(self) -> None:
        source = (ROOT / "scripts/bootstrap_superadmin.py").read_text(encoding="utf-8")
        for token in (
            "--confirm-create",
            "ADMIN_PASSWORD",
            "databasen har allerede en aktiv administrator",
            'role="superadmin"',
            "must_change_password=True",
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
