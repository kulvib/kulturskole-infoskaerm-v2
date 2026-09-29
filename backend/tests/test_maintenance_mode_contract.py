from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from service1 import auth
from service1.maintenance_state import MaintenanceSnapshot
from service1.models import MaintenanceState, User


def _user(role: str) -> User:
    return User(
        id=1,
        username=role,
        hashed_password="unused",
        email=f"{role}@example.test",
        role=role,
        is_active=True,
        must_change_password=False,
    )


def _request(path: str, actor=None, impersonation=False):
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        state=SimpleNamespace(real_actor=actor, impersonation_active=impersonation),
    )


def test_maintenance_model_is_singleton_and_migration_advances_schema_head():
    table = MaintenanceState.__table__
    assert table.name == "maintenance_state"
    assert table.c.id.primary_key
    assert table.c.message.type.length == 500
    constraints = {constraint.name for constraint in table.constraints}
    assert "ck_maintenance_state_singleton_id" in constraints

    migration = open("backend/migrations/versions/20260929_58a_maintenance_mode.py", encoding="utf-8").read()
    contract = open("backend/scripts/display_schema_contract.py", encoding="utf-8").read()
    runner = open("backend/scripts/run_migrations.py", encoding="utf-8").read()
    assert 'revision = "20260929_58a_maintenance"' in migration
    assert 'down_revision = "20260929_57a_impersonation"' in migration
    assert 'EXPECTED_HEAD_REVISION = "20260929_58a_maintenance"' in contract
    assert 'REVIEWED_MAINTENANCE_REVISION = "20260929_58a_maintenance"' in runner
    assert 'maintenance_revision.down_revision != REVIEWED_IMPERSONATION_REVISION' in runner


def test_human_access_fails_closed_for_regular_users_but_allows_superadmin_and_impersonation_stop(monkeypatch):
    state = MaintenanceSnapshot(enabled=True, message="Planlagt vedligeholdelse")
    monkeypatch.setattr(auth, "get_maintenance_snapshot", lambda _session: state)

    regular = _user("bruger")
    with pytest.raises(HTTPException) as blocked:
        auth._enforce_human_maintenance_access(_request("/api/clients"), object(), regular)
    assert blocked.value.status_code == 503
    assert blocked.value.detail == "Planlagt vedligeholdelse"

    superadmin = _user("superadmin")
    auth._enforce_human_maintenance_access(_request("/api/clients"), object(), superadmin)

    auth._enforce_human_maintenance_access(_request("/api/auth/me"), object(), regular)

    admin = _user("admin")
    auth._enforce_human_maintenance_access(
        _request("/api/auth/impersonation/stop", actor=admin, impersonation=True),
        object(),
        regular,
    )


def test_refresh_preserves_session_continuity_during_maintenance():
    source = open("backend/service1/auth.py", encoding="utf-8").read()
    function = source[source.index("def refresh_access_token"):source.index('@router.post("/logout")')]
    assert "_maintenance_snapshot_or_503" not in function
    assert "_create_refresh_token(" in function


def test_client_principal_path_is_resolved_before_human_maintenance_gate():
    source = open("backend/service1/auth.py", encoding="utf-8").read()
    function = source[source.index("def get_current_user_or_client"):source.index("def principal_is_client")]
    assert function.index('payload.get("principal") == "client"') < function.index("_enforce_human_maintenance_access")


def test_maintenance_mutation_is_superadmin_reauthenticated_audited_and_no_store():
    router = open("backend/service1/routers/maintenance.py", encoding="utf-8").read()
    assert 'if not actor.is_superadmin:' in router
    assert 'bucket="maintenance-password"' in router
    assert 'verify_password(password, actor.hashed_password)' in router
    assert 'action="maintenance_enabled" if payload.enabled else "maintenance_disabled"' in router
    assert 'response.headers["Cache-Control"] = "no-store, max-age=0"' in router
    assert 'scope": "human_user_access_only"' in router


def test_websocket_user_auth_is_maintenance_gated_after_client_short_circuit():
    source = open("backend/service1/auth.py", encoding="utf-8").read()
    function = source[source.index("def verify_ws_token"):]
    assert function.index('payload.get("principal") == "client"') < function.index("get_maintenance_snapshot(session)")
    assert "if state.enabled and not user.is_superadmin" in function
