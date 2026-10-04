from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest

pytest.importorskip("passlib")

from service1.livestream_media_capability import (
    AUDIENCE,
    ISSUER,
    issue_livestream_media_capability,
    verify_livestream_media_capability,
)
from service1.auth import SECRET_KEY


def test_media_capability_is_bound_to_parent_session_expiry_and_context() -> None:
    parent_expiry = datetime.now(timezone.utc) + timedelta(seconds=20)
    token, expires_at = issue_livestream_media_capability(
        client_id=7,
        principal=SimpleNamespace(id=3),
        auth_session_binding="session-binding-abc",
        parent_session_expires_at=parent_expiry,
    )
    assert expires_at <= parent_expiry
    claims = verify_livestream_media_capability(token, client_id=7)
    assert claims["auth_session_binding"] == "session-binding-abc"
    assert claims["parent_session_exp"] == int(parent_expiry.timestamp())
    assert claims["exp"] <= int(parent_expiry.timestamp())


def test_media_capability_signature_and_scope_stay_fail_closed() -> None:
    token, _ = issue_livestream_media_capability(
        client_id=7,
        principal=SimpleNamespace(id=3),
        auth_session_binding="session-binding-abc",
        parent_session_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    claims = jwt.decode(token, SECRET_KEY, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER)
    assert claims["purpose"] == "livestream_media_read"
    assert claims["client_id"] == 7
