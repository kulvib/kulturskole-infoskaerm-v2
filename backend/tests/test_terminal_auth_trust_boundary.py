from __future__ import annotations

import base64
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import jwt

from service1.terminal_v2 import (
    ADMIN_STEP_UP_AUDIENCE,
    DOMAIN_TOKEN_ISSUER,
    TERMINAL_AUTH_ALGORITHM,
    TERMINAL_AUTH_ISSUER,
    _terminal_auth_signing_key,
    create_terminal_domain_token,
    verify_admin_terminal_step_up,
    verify_admin_terminal_step_up_token,
)


def b64_key(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


class TerminalAuthTrustBoundaryTests(unittest.TestCase):
    def test_agent_issuer_preserves_client_credential_contract(self) -> None:
        self.assertEqual(DOMAIN_TOKEN_ISSUER, "planiq-display-api")
        self.assertEqual(TERMINAL_AUTH_ISSUER, "clientflow-terminal-auth")
        self.assertNotEqual(DOMAIN_TOKEN_ISSUER, TERMINAL_AUTH_ISSUER)

    def test_terminal_auth_key_is_required_and_has_exact_size(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLIENTFLOW_TERMINAL_AUTH_KEY_B64", None)
            with self.assertRaises(HTTPException) as missing:
                _terminal_auth_signing_key()
            self.assertEqual(missing.exception.status_code, 503)

        with patch.dict(os.environ, {"CLIENTFLOW_TERMINAL_AUTH_KEY_B64": b64_key(7)}):
            self.assertEqual(_terminal_auth_signing_key(), bytes([7]) * 32)

        short = base64.urlsafe_b64encode(b"too-short").decode("ascii").rstrip("=")
        with patch.dict(os.environ, {"CLIENTFLOW_TERMINAL_AUTH_KEY_B64": short}):
            with self.assertRaises(HTTPException) as invalid:
                _terminal_auth_signing_key()
            self.assertEqual(invalid.exception.status_code, 503)

    def test_agent_token_is_signed_only_by_terminal_key(self) -> None:
        terminal_key = bytes([11]) * 32
        wrong_key = bytes([12]) * 32
        credential = SimpleNamespace(
            client_id=23,
            id="544b7d28-a94e-4ddd-b332-9f57c38f5361",
            token_version=4,
        )
        with patch.dict(os.environ, {"CLIENTFLOW_TERMINAL_AUTH_KEY_B64": b64_key(11)}):
            token, _ = create_terminal_domain_token(credential)

        claims = jwt.decode(
            token,
            terminal_key,
            algorithms=[TERMINAL_AUTH_ALGORITHM],
            audience="clientflow-domain:terminal",
            issuer=DOMAIN_TOKEN_ISSUER,
        )
        self.assertEqual(claims["client_id"], 23)
        self.assertEqual(claims["domain"], "terminal")
        with self.assertRaises(jwt.PyJWTError):
            jwt.decode(
                token,
                wrong_key,
                algorithms=[TERMINAL_AUTH_ALGORITHM],
                audience="clientflow-domain:terminal",
                issuer=DOMAIN_TOKEN_ISSUER,
            )

    def test_admin_step_up_uses_terminal_issuer_key_and_session_binding(self) -> None:
        user = SimpleNamespace(
            id=4,
            username="admin",
            hashed_password="not-used",
            token_version=9,
            is_superadmin=True,
            is_active=True,
        )
        with patch.dict(os.environ, {"CLIENTFLOW_TERMINAL_AUTH_KEY_B64": b64_key(21)}), patch(
            "service1.terminal_v2.verify_password", return_value=True
        ):
            verified_at, token, _ = verify_admin_terminal_step_up(
                user,
                "password",
                auth_session_binding="login-binding-1",
            )
            self.assertIsNotNone(verified_at)
            claims = jwt.decode(
                token,
                bytes([21]) * 32,
                algorithms=[TERMINAL_AUTH_ALGORITHM],
                audience=ADMIN_STEP_UP_AUDIENCE,
                issuer=TERMINAL_AUTH_ISSUER,
            )
            self.assertEqual(claims["purpose"], "terminal_admin_step_up")
            self.assertEqual(claims["session_binding"], "login-binding-1")
            self.assertIsNotNone(
                verify_admin_terminal_step_up_token(
                    user, token, auth_session_binding="login-binding-1"
                )
            )
            with self.assertRaises(HTTPException):
                verify_admin_terminal_step_up_token(
                    user, token, auth_session_binding="other-login-binding"
                )


if __name__ == "__main__":
    unittest.main()
