from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = REPO_ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release import enrollment as release_enrollment
from clientflow_release.constants import DOMAIN_NAMES
from clientflow_release.update_auth import generate_update_key


class EnrollmentIssuerContractTests(unittest.TestCase):
    def _response(self, *, update_key_id: str = "0123456789abcdef0123456789abcdef") -> dict:
        issuer_by_domain = {
            "status": "planiq-display-api",
            "display": "planiq-display-api",
            "system": "planiq-display-api",
            "livestream": "clientflow-api",
            "terminal": "planiq-display-api",
            "remote_desktop": "planiq-display-api",
        }
        credentials = [
            {
                "domain": domain,
                "credential_id": str(uuid.uuid4()),
                "token_issuer": issuer_by_domain[domain],
            }
            for domain in DOMAIN_NAMES
        ]
        terminal_credential_id = next(
            row["credential_id"] for row in credentials if row["domain"] == "terminal"
        )
        return {
            "client_id": 23,
            "credentials": credentials,
            "root_terminal_broker": {
                "terminal_credential_id": terminal_credential_id,
                "key_id": "test-root-key",
                "algorithm": "RS256",
                "audience": "clientflow-root-terminal-broker",
                "issuer": "clientflow-backend",
                "verification_key_b64": "dGVzdA==",
            },
            "system_encryption_key_id": "test-system-key-id",
            "update_auth": {
                "credential_id": str(uuid.uuid4()),
                "key_id": update_key_id,
                "algorithm": "Ed25519",
                "token_audience": "urn:planiq:clientflow-update:token",
                "access_token_issuer": "planiq-clientflow-update",
                "access_token_audience": "urn:planiq:clientflow-update:resource",
            },
            "status": "pending",
            "name": "CI screen",
        }

    def _binding(self) -> dict:
        return {
            "release_id": "clientflow-1.3.3-seq-1204",
            "version": "1.3.3",
            "release_sequence": 1204,
            "bundle_sha256": "a" * 64,
            "bundle_size": 123456,
            "release_approval_reference": "clientflow-1.3.3-seq-1204/test",
            "release_candidate_sha256": "b" * 64,
            "source_commit": "c" * 40,
        }

    def _claim(self, response: dict, *, enrollment_code="CF-TEST-TEST-TEST", authorization="cf-fresh-v1.payload.signature"):
        captured: dict = {}

        def fake_post(_url, payload, *, ca_file):
            captured.update(payload)
            return response

        with patch.object(release_enrollment, "_post_json", side_effect=fake_post):
            actual = release_enrollment.claim(
                backend_url="https://display.example.invalid",
                enrollment_code=enrollment_code,
                fresh_install_authorization=authorization,
                fresh_install_binding=self._binding(),
                install_id=str(uuid.uuid4()),
                seed=bytes(range(32)),
                public_key_pem="-----BEGIN PUBLIC KEY-----\nplaceholder\n-----END PUBLIC KEY-----",
                update_auth_public_key_pem="-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAzU6003WsShJbh/Yk3H4tAwXd4ep+A128YEJSAYemC68=\n-----END PUBLIC KEY-----",
                name="CI screen",
                locality=None,
                ca_file=None,
            )
        return actual, captured

    def test_claim_accepts_per_domain_issuers_without_top_level_issuer(self) -> None:
        response = self._response()
        actual, captured = self._claim(response)
        self.assertEqual(actual, response)
        self.assertNotIn("token_issuer", actual)
        self.assertEqual(captured["enrollment_code"], "CF-TEST-TEST-TEST")
        self.assertEqual(captured["fresh_install_authorization"], "cf-fresh-v1.payload.signature")
        self.assertEqual(captured["fresh_install_binding"], self._binding())
        self.assertNotEqual(
            next(row["token_issuer"] for row in actual["credentials"] if row["domain"] == "livestream"),
            next(row["token_issuer"] for row in actual["credentials"] if row["domain"] == "status"),
        )

    def test_claim_can_send_receipt_resume_without_one_time_authorities(self) -> None:
        response = self._response()
        actual, captured = self._claim(response, enrollment_code=None, authorization=None)
        self.assertEqual(actual, response)
        self.assertIsNone(captured["enrollment_code"])
        self.assertIsNone(captured["fresh_install_authorization"])
        self.assertEqual(captured["fresh_install_binding"], self._binding())


    def test_complete_carries_same_release_binding_as_claim_resume(self) -> None:
        captured: dict = {}

        def fake_post(_url, payload, *, ca_file):
            captured.update(payload)
            return {"ok": True}

        with patch.object(release_enrollment, "_post_json", side_effect=fake_post):
            result = release_enrollment.complete(
                backend_url="https://display.example.invalid",
                install_id=str(uuid.uuid4()),
                seed=bytes(range(32)),
                fresh_install_binding=self._binding(),
                ca_file=None,
            )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["fresh_install_binding"], self._binding())
        self.assertIn("resume_proof", captured)

    def test_persist_enrollment_keeps_each_domain_issuer(self) -> None:
        seed = bytes(range(32))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            update_private_key = root / "update-private-key.pem"
            _update_public, update_key_id, _jwk, _jkt = generate_update_key(update_private_key)
            response = self._response(update_key_id=update_key_id)
            private_key = root / "system-private-key.pem"
            private_key.write_text("test-private-key", encoding="utf-8")
            private_key.chmod(0o600)
            etc_root = root / "etc-clientflow"
            with patch.object(
                release_enrollment,
                "_system_key_id",
                return_value=response["system_encryption_key_id"],
            ):
                release_enrollment.persist_enrollment(
                    response,
                    seed=seed,
                    backend_url="https://display.example.invalid",
                    kiosk_user="clientflow",
                    etc_root=etc_root,
                    private_key=private_key,
                    update_private_key=update_private_key,
                )

            status = json.loads((etc_root / "credentials/status.json").read_text(encoding="utf-8"))
            livestream = json.loads((etc_root / "credentials/livestream.json").read_text(encoding="utf-8"))
            self.assertEqual(status["token_issuer"], "planiq-display-api")
            self.assertEqual(livestream["token_issuer"], "clientflow-api")
            self.assertNotEqual(status["token_issuer"], livestream["token_issuer"])

    def test_claim_rejects_missing_domain_issuer(self) -> None:
        response = self._response()
        response["credentials"][0].pop("token_issuer")
        with self.assertRaisesRegex(release_enrollment.EnrollmentError, "mangler token issuer"):
            self._claim(response)


if __name__ == "__main__":
    unittest.main()
