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

    def test_claim_accepts_per_domain_issuers_without_top_level_issuer(self) -> None:
        response = self._response()
        install_id = str(uuid.uuid4())
        seed = bytes(range(32))
        with patch.object(release_enrollment, "_post_json", return_value=response):
            actual = release_enrollment.claim(
                backend_url="https://display.example.invalid",
                enrollment_code="CF-TEST-TEST-TEST",
                install_id=install_id,
                seed=seed,
                public_key_pem="-----BEGIN PUBLIC KEY-----\nplaceholder\n-----END PUBLIC KEY-----",
                update_auth_public_key_pem="-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAzU6003WsShJbh/Yk3H4tAwXd4ep+A128YEJSAYemC68=\n-----END PUBLIC KEY-----",
                name="CI screen",
                locality=None,
                ca_file=None,
            )
        self.assertEqual(actual, response)
        self.assertNotIn("token_issuer", actual)
        self.assertNotEqual(
            next(row["token_issuer"] for row in actual["credentials"] if row["domain"] == "livestream"),
            next(row["token_issuer"] for row in actual["credentials"] if row["domain"] == "status"),
        )

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
        with patch.object(release_enrollment, "_post_json", return_value=response):
            with self.assertRaisesRegex(release_enrollment.EnrollmentError, "mangler token issuer"):
                release_enrollment.claim(
                    backend_url="https://display.example.invalid",
                    enrollment_code="CF-TEST-TEST-TEST",
                    install_id=str(uuid.uuid4()),
                    seed=bytes(range(32)),
                    public_key_pem="-----BEGIN PUBLIC KEY-----\nplaceholder\n-----END PUBLIC KEY-----",
                    update_auth_public_key_pem="-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAzU6003WsShJbh/Yk3H4tAwXd4ep+A128YEJSAYemC68=\n-----END PUBLIC KEY-----",
                    name="CI screen",
                    locality=None,
                    ca_file=None,
                )


if __name__ == "__main__":
    unittest.main()
