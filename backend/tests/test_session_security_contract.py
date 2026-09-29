import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-that-is-long-enough-for-auth-tests")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("ENVIRONMENT", "development")

from service1 import auth
from service1.models import RefreshToken, User


def _user(user_id: int = 1) -> User:
    return User(
        id=user_id,
        username=f"user{user_id}",
        hashed_password="hashed",
        email=f"user{user_id}@example.test",
        full_name=f"User {user_id}",
        role="admin",
        organization_id=10,
        is_active=True,
        must_change_password=False,
        token_version=0,
    )


def _row(
    *,
    row_id: int,
    user_id: int,
    session_id: str,
    token: str,
    created_minutes_ago: int = 0,
    impersonated_user_id: int | None = None,
) -> RefreshToken:
    now = datetime.now(timezone.utc)
    return RefreshToken(
        id=row_id,
        user_id=user_id,
        token_hash=auth._hash_refresh_token(token),
        expires_at=(now + timedelta(hours=2)).replace(tzinfo=None),
        session_expires_at=(now + timedelta(hours=4)).replace(tzinfo=None),
        session_id=session_id,
        impersonated_user_id=impersonated_user_id,
        created_ip="203.0.113.10",
        user_agent="Contract Browser",
        created_at=(now - timedelta(minutes=created_minutes_ago)).replace(tzinfo=None),
    )


class _RowsResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, current_row: RefreshToken, rows):
        self.current_row = current_row
        self.rows = list(rows)
        self.added = []
        self.committed = False
        self.rolled_back = False

    def get(self, model, object_id):
        if model is RefreshToken and object_id == self.current_row.id:
            return self.current_row
        return None

    def exec(self, _statement):
        return _RowsResult(self.rows)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _request(actor: User, current_row: RefreshToken, raw_refresh_token: str):
    return SimpleNamespace(
        state=SimpleNamespace(
            real_actor=actor,
            current_user=actor,
            impersonation_active=False,
            refresh_token_row_id=current_row.id,
        ),
        cookies={auth.REFRESH_COOKIE_NAME: raw_refresh_token},
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )


def test_session_list_marks_current_session_once_and_never_caches():
    actor = _user()
    current_token = "current-refresh-token"
    current = _row(
        row_id=1,
        user_id=actor.id,
        session_id="a" * 32,
        token=current_token,
        created_minutes_ago=1,
    )
    other = _row(
        row_id=2,
        user_id=actor.id,
        session_id="b" * 32,
        token="other-refresh-token",
        created_minutes_ago=10,
        impersonated_user_id=7,
    )
    duplicate_other = _row(
        row_id=3,
        user_id=actor.id,
        session_id="b" * 32,
        token="duplicate-refresh-token",
        created_minutes_ago=20,
    )
    session = _FakeSession(current, [current, other, duplicate_other])
    response = Response()

    result = auth.list_active_sessions(
        response=response,
        request=_request(actor, current, current_token),
        session=session,
        current_user=actor,
    )

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert len(result) == 2
    assert sum(1 for row in result if row.current) == 1
    assert result[0].session_id == current.session_id
    assert result[0].current is True
    assert next(row for row in result if row.session_id == other.session_id).impersonation_active is True


def test_current_session_cannot_be_revoked_through_remote_session_endpoint():
    actor = _user()
    raw_token = "current-refresh-token"
    current = _row(
        row_id=1,
        user_id=actor.id,
        session_id="a" * 32,
        token=raw_token,
    )
    session = _FakeSession(current, [])

    with pytest.raises(HTTPException) as exc:
        auth.revoke_active_session(
            payload=auth.SessionRevokeRequest(session_id=current.session_id, password="password"),
            response=Response(),
            request=_request(actor, current, raw_token),
            session=session,
            current_user=actor,
        )

    assert exc.value.status_code == 400
    assert session.committed is False


def test_remote_revocation_requires_current_password_and_revokes_only_target_rows(monkeypatch):
    actor = _user()
    raw_token = "current-refresh-token"
    current = _row(
        row_id=1,
        user_id=actor.id,
        session_id="a" * 32,
        token=raw_token,
    )
    target = _row(
        row_id=2,
        user_id=actor.id,
        session_id="b" * 32,
        token="target-refresh-token",
    )
    session = _FakeSession(current, [target])
    password_checks = []

    monkeypatch.setattr(auth, "assert_key_not_limited", lambda **_kwargs: None)
    monkeypatch.setattr(auth, "clear_key_rate_limit", lambda **_kwargs: None)
    monkeypatch.setattr(
        auth,
        "verify_password",
        lambda password, hashed: password_checks.append((password, hashed)) or True,
    )

    response = Response()
    result = auth.revoke_active_session(
        payload=auth.SessionRevokeRequest(session_id=target.session_id, password="correct-password"),
        response=response,
        request=_request(actor, current, raw_token),
        session=session,
        current_user=actor,
    )

    assert password_checks == [("correct-password", actor.hashed_password)]
    assert target.revoked_at is not None
    assert current.revoked_at is None
    assert result.revoked_count == 1
    assert session.committed is True
    assert response.headers["Cache-Control"] == "no-store"


def test_revoke_other_sessions_preserves_current_and_revokes_other_active_rows(monkeypatch):
    actor = _user()
    raw_token = "current-refresh-token"
    current = _row(
        row_id=1,
        user_id=actor.id,
        session_id="a" * 32,
        token=raw_token,
    )
    other = _row(
        row_id=2,
        user_id=actor.id,
        session_id="b" * 32,
        token="other-refresh-token",
    )
    session = _FakeSession(current, [other])

    monkeypatch.setattr(auth, "assert_key_not_limited", lambda **_kwargs: None)
    monkeypatch.setattr(auth, "clear_key_rate_limit", lambda **_kwargs: None)
    monkeypatch.setattr(auth, "verify_password", lambda _password, _hashed: True)

    response = Response()
    result = auth.revoke_other_sessions(
        payload=auth.SessionRevokeOthersRequest(password="correct-password"),
        response=response,
        request=_request(actor, current, raw_token),
        session=session,
        current_user=actor,
    )

    assert other.revoked_at is not None
    assert current.revoked_at is None
    assert result.revoked_count == 1
    assert session.committed is True
    assert response.headers["Cache-Control"] == "no-store"


def test_wrong_reauthentication_password_is_forbidden_without_revoking(monkeypatch):
    actor = _user()
    raw_token = "current-refresh-token"
    current = _row(
        row_id=1,
        user_id=actor.id,
        session_id="a" * 32,
        token=raw_token,
    )
    target = _row(
        row_id=2,
        user_id=actor.id,
        session_id="b" * 32,
        token="target-refresh-token",
    )
    session = _FakeSession(current, [target])
    attempts = []
    audits = []

    monkeypatch.setattr(auth, "assert_key_not_limited", lambda **_kwargs: None)
    monkeypatch.setattr(auth, "verify_password", lambda _password, _hashed: False)
    monkeypatch.setattr(auth, "record_key_attempt", lambda **kwargs: attempts.append(kwargs))
    monkeypatch.setattr(auth, "commit_audit_log", lambda *_args, **kwargs: audits.append(kwargs))

    with pytest.raises(HTTPException) as exc:
        auth.revoke_active_session(
            payload=auth.SessionRevokeRequest(session_id=target.session_id, password="wrong-password"),
            response=Response(),
            request=_request(actor, current, raw_token),
            session=session,
            current_user=actor,
        )

    assert exc.value.status_code == 403
    assert target.revoked_at is None
    assert current.revoked_at is None
    assert session.committed is False
    assert len(attempts) == 1
    assert audits and audits[0]["action"] == "session_reauthentication_failed"


def test_session_security_is_blocked_during_user_switch():
    actor = _user(1)
    effective = _user(2)
    request = SimpleNamespace(
        state=SimpleNamespace(real_actor=actor, current_user=effective, impersonation_active=True)
    )

    with pytest.raises(HTTPException) as exc:
        auth._session_security_actor(request, effective)

    assert exc.value.status_code == 409


def test_session_security_routes_are_owner_scoped_and_password_protected():
    source = open("backend/service1/auth.py", encoding="utf-8").read()

    assert '@router.get("/sessions"' in source
    assert '@router.post("/sessions/revoke"' in source
    assert '@router.post("/sessions/revoke-others"' in source
    assert "RefreshToken.user_id == int(actor.id)" in source
    assert "RefreshToken.session_id == target_session_id" in source
    assert "_require_session_security_password(" in source
    assert 'detail="Brug Log ud for at afslutte den aktuelle session"' in source
    assert 'response.headers["Cache-Control"] = "no-store"' in source
    assert 'entity_label=target_session_id' not in source
    assert 'entity_label=current_session_id' not in source
