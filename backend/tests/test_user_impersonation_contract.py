import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-that-is-long-enough-for-auth-tests")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("ENVIRONMENT", "development")

from service1 import auth
from service1.models import RefreshToken, User


def _user(*, user_id: int, username: str, role: str, organization_id: int | None) -> User:
    return User(
        id=user_id,
        username=username,
        hashed_password="unused",
        email=f"{username}@example.test",
        full_name=username.title(),
        role=role,
        organization_id=organization_id,
        is_active=True,
        must_change_password=False,
        token_version=0,
    )


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeSession:
    def __init__(self, *objects):
        self._objects = {(type(obj), obj.id): obj for obj in objects}
        self._refresh_rows = [obj for obj in objects if isinstance(obj, RefreshToken)]

    def get(self, model, object_id):
        return self._objects.get((model, object_id))

    def exec(self, _statement):
        active = next((row for row in reversed(self._refresh_rows) if row.revoked_at is None), None)
        return _FakeResult(active)


def _active_row(*, row_id: int, actor_id: int, target_id: int | None = None) -> RefreshToken:
    now = datetime.now(timezone.utc)
    return RefreshToken(
        id=row_id,
        user_id=actor_id,
        impersonated_user_id=target_id,
        token_hash="a" * 64,
        expires_at=(now + timedelta(hours=2)).replace(tzinfo=None),
        session_expires_at=(now + timedelta(hours=4)).replace(tzinfo=None),
        session_id="stable-session-id",
    )


def _payload(*, row: RefreshToken, actor: User, effective: User) -> dict:
    session_expiry = auth._refresh_session_expires_at(row)
    payload = {
        "sub": effective.username,
        "uid": effective.id,
        "role": effective.role,
        "token_version": effective.token_version,
        "sid": row.session_id,
        "session_expires_at": auth._session_expiry_iso(session_expiry),
    }
    if actor.id != effective.id:
        payload.update(
            {
                "actor_uid": actor.id,
                "actor_sub": actor.username,
                "actor_token_version": actor.token_version,
            }
        )
    return payload


def test_admin_may_only_switch_within_own_org_and_not_to_privileged_viewer_roles():
    actor = _user(user_id=1, username="admin", role="admin", organization_id=10)
    same_org_user = _user(user_id=2, username="teacher", role="bruger", organization_id=10)
    auth._assert_impersonation_allowed(actor, same_org_user)

    with pytest.raises(HTTPException) as cross_org:
        auth._assert_impersonation_allowed(
            actor,
            _user(user_id=3, username="other", role="bruger", organization_id=11),
        )
    assert cross_org.value.status_code == 403

    for forbidden_role in ("superadmin", "viewer"):
        with pytest.raises(HTTPException) as forbidden:
            auth._assert_impersonation_allowed(
                actor,
                _user(user_id=4, username=forbidden_role, role=forbidden_role, organization_id=10),
            )
        assert forbidden.value.status_code == 403


def test_regular_user_cannot_switch_and_pending_target_is_fail_closed():
    regular = _user(user_id=1, username="regular", role="bruger", organization_id=10)
    target = _user(user_id=2, username="target", role="bruger", organization_id=10)
    with pytest.raises(HTTPException) as denied:
        auth._assert_impersonation_allowed(regular, target)
    assert denied.value.status_code == 403

    admin = _user(user_id=3, username="admin", role="admin", organization_id=10)
    target.must_change_password = True
    with pytest.raises(HTTPException) as pending:
        auth._assert_impersonation_allowed(admin, target)
    assert pending.value.status_code == 400
    auth._assert_impersonation_allowed(admin, target, allow_pending_target=True)


def test_impersonated_access_context_is_bound_to_active_refresh_row_and_real_actor():
    actor = _user(user_id=1, username="admin", role="admin", organization_id=10)
    target = _user(user_id=2, username="teacher", role="bruger", organization_id=10)
    row = _active_row(row_id=77, actor_id=actor.id, target_id=target.id)
    session = _FakeSession(actor, target, row)
    request = SimpleNamespace(state=SimpleNamespace())

    resolved = auth._resolve_user_from_payload(_payload(row=row, actor=actor, effective=target), session, request)

    assert resolved.id == target.id
    assert request.state.real_actor.id == actor.id
    assert request.state.current_user.id == target.id
    assert request.state.impersonation_active is True
    assert request.state.refresh_token_row_id == row.id

    row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with pytest.raises(HTTPException) as revoked:
        auth._resolve_user_from_payload(_payload(row=row, actor=actor, effective=target), session)
    assert revoked.value.status_code == 401


def test_normal_refresh_rotation_keeps_access_context_valid_with_same_session_id():
    actor = _user(user_id=1, username="admin", role="admin", organization_id=10)
    old_row = _active_row(row_id=77, actor_id=actor.id)
    old_payload = _payload(row=old_row, actor=actor, effective=actor)
    old_row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    new_row = _active_row(row_id=78, actor_id=actor.id)
    new_row.session_id = old_row.session_id
    session = _FakeSession(actor, old_row, new_row)

    resolved = auth._resolve_user_from_payload(old_payload, session)
    assert resolved.id == actor.id


def test_access_context_rejects_refresh_row_target_mismatch():
    actor = _user(user_id=1, username="admin", role="admin", organization_id=10)
    target = _user(user_id=2, username="teacher", role="bruger", organization_id=10)
    other = _user(user_id=3, username="other", role="bruger", organization_id=10)
    row = _active_row(row_id=88, actor_id=actor.id, target_id=other.id)
    session = _FakeSession(actor, target, other, row)

    with pytest.raises(HTTPException) as mismatch:
        auth._resolve_user_from_payload(_payload(row=row, actor=actor, effective=target), session)
    assert mismatch.value.status_code == 401


def test_migration_and_schema_contract_include_impersonation_refresh_binding():
    migration = open("backend/migrations/versions/20260929_57a_user_impersonation.py", encoding="utf-8").read()
    contract = open("backend/scripts/display_schema_contract.py", encoding="utf-8").read()
    runner = open("backend/scripts/run_migrations.py", encoding="utf-8").read()

    assert 'revision = "20260929_57a_impersonation"' in migration
    assert 'down_revision = "20260922_56a_calendar_rev"' in migration
    assert 'EXPECTED_HEAD_REVISION = "20260929_57a_impersonation"' in contract
    assert 'session_id' in migration
    assert 'ix_refresh_tokens_session_id' in contract
    assert 'REVIEWED_IMPERSONATION_REVISION = "20260929_57a_impersonation"' in runner
    assert 'head != REVIEWED_IMPERSONATION_REVISION' in runner
