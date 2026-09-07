from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("PASSWORD_RESET_FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")
os.environ.setdefault("JWT_ISSUER", "planiq-display-api")
os.environ.setdefault("JWT_AUDIENCE", "planiq-display")
os.environ.setdefault("HLS_BASE_DIR", "/tmp/planiq-display-ci-hls")

from service1.auth import (
    ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER,
    JWT_REQUIRED_CLAIMS,
    SECRET_KEY,
    create_access_token,
    _decode_token_or_raise,
)


class JwtAccessTokenContractTests(unittest.TestCase):
    def _valid_payload(self) -> dict:
        token = create_access_token({"sub": "ci-user", "uid": 1, "token_version": 0})
        return jwt.decode(token, options={"verify_signature": False})

    def _encode(self, payload: dict) -> str:
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def _assert_rejected(self, payload: dict) -> None:
        with self.assertRaises(HTTPException):
            _decode_token_or_raise(self._encode(payload))

    def test_created_token_has_all_registered_claims(self) -> None:
        payload = self._valid_payload()
        self.assertEqual(payload["iss"], JWT_ISSUER)
        self.assertEqual(payload["aud"], JWT_AUDIENCE)
        for claim in JWT_REQUIRED_CLAIMS:
            self.assertIn(claim, payload)
        self.assertTrue(payload["jti"])

    def test_wrong_issuer_is_rejected(self) -> None:
        payload = self._valid_payload()
        payload["iss"] = "wrong-issuer"
        self._assert_rejected(payload)

    def test_wrong_audience_is_rejected(self) -> None:
        payload = self._valid_payload()
        payload["aud"] = "wrong-audience"
        self._assert_rejected(payload)

    def test_expired_token_is_rejected(self) -> None:
        payload = self._valid_payload()
        payload["exp"] = datetime.now(timezone.utc) - timedelta(minutes=2)
        self._assert_rejected(payload)

    def test_future_nbf_is_rejected(self) -> None:
        payload = self._valid_payload()
        payload["nbf"] = datetime.now(timezone.utc) + timedelta(minutes=2)
        payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=5)
        self._assert_rejected(payload)

    def test_missing_required_claim_is_rejected(self) -> None:
        payload = self._valid_payload()
        payload.pop("jti")
        self._assert_rejected(payload)


if __name__ == "__main__":
    unittest.main()
