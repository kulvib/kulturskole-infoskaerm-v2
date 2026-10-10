"""Fleet-scale realtime wakes are client-scoped; authorization stays canonical."""
from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

from service1 import ui_realtime
from service1.routers import clients as clients_router


def _principal():
    return SimpleNamespace(id=17, is_superadmin=True, role="superadmin", organization_id=9)


def test_scoped_detail_does_not_wake_for_another_client():
    first = ui_realtime.issue_ui_realtime_capability(_principal(), client_id=1001)
    claims = ui_realtime.verify_ui_realtime_capability(first["capability"])
    ui_realtime.notify_ui_state_changed(organization_id=9, client_id=1002)
    assert ui_realtime.wait_for_ui_change(
        claims=claims, after=first["generation"], timeout=0
    ) == first["generation"]
    ui_realtime.notify_ui_state_changed(organization_id=9, client_id=1001)
    assert ui_realtime.wait_for_ui_change(
        claims=claims, after=first["generation"], timeout=0
    ) > first["generation"]


def test_unscoped_control_room_still_wakes_for_entire_organization():
    cap = ui_realtime.issue_ui_realtime_capability(
        SimpleNamespace(id=31, is_superadmin=False, role="admin", organization_id=9)
    )
    claims = ui_realtime.verify_ui_realtime_capability(cap["capability"])
    ui_realtime.notify_ui_state_changed(organization_id=9, client_id=2011)
    assert (
        ui_realtime.wait_for_ui_change(claims=claims, after=cap["generation"], timeout=0)
        > cap["generation"]
    )


def test_scoped_wait_is_db_free_and_returns_current_generation():
    cap = ui_realtime.issue_ui_realtime_capability(_principal(), client_id=3011)
    claims = ui_realtime.verify_ui_realtime_capability(cap["capability"])
    result = ui_realtime.wait_for_ui_change(claims=claims, after=cap["generation"], timeout=0)
    assert result == cap["generation"]


def test_invalid_client_id_claim_is_fail_closed():
    claims = jwt.decode(
        ui_realtime.issue_ui_realtime_capability(_principal(), client_id=51)["capability"],
        ui_realtime.SECRET_KEY,
        algorithms=["HS256"],
        audience=ui_realtime.AUDIENCE,
        issuer=ui_realtime.ISSUER,
    )
    claims["client_id"] = "51"
    tampered = jwt.encode(claims, ui_realtime.SECRET_KEY, algorithm="HS256")
    with pytest.raises(HTTPException) as error:
        ui_realtime.verify_ui_realtime_capability(tampered)
    assert error.value.status_code == 403


class _FakeSession:
    def __init__(self, client):
        self.client = client

    def get(self, model, client_id):
        assert model is clients_router.Client
        return self.client if self.client is not None and self.client.id == client_id else None


def test_scoped_capability_issuance_enforces_canonical_client_read_access():
    user = SimpleNamespace(
        id=41, is_superadmin=False, is_admin=True, role="admin", organization_id=11
    )
    client = SimpleNamespace(
        id=111, organization_id=12, status="approved", deleted_at=None
    )
    with pytest.raises(HTTPException) as error:
        clients_router.create_control_room_realtime_capability(
            client_id=111, session=_FakeSession(client), user=user
        )
    assert error.value.status_code == 403


def test_scoped_capability_issuance_succeeds_for_authorized_client():
    user = SimpleNamespace(
        id=42, is_superadmin=False, is_admin=True, role="admin", organization_id=11
    )
    client = SimpleNamespace(
        id=112, organization_id=11, status="approved", deleted_at=None
    )
    capability = clients_router.create_control_room_realtime_capability(
        client_id=112, session=_FakeSession(client), user=user
    )
    claims = ui_realtime.verify_ui_realtime_capability(capability["capability"])
    assert claims["client_id"] == 112


def test_scoped_capability_does_not_invent_missing_clients():
    with pytest.raises(HTTPException) as error:
        clients_router.create_control_room_realtime_capability(
            client_id=999, session=_FakeSession(None), user=_principal()
        )
    assert error.value.status_code == 404


def test_one_thousand_scoped_subscriptions_only_receive_their_own_client_events():
    """A fleet-wide status burst must not invalidate unrelated detail pages.

    These waits are deliberately zero-timeout and use no database session;
    the workload measures scope isolation, not production throughput.
    """
    principal = _principal()
    base_client_id = 50_000
    subscriptions = [
        ui_realtime.issue_ui_realtime_capability(principal, client_id=base_client_id + i)
        for i in range(1_000)
    ]
    target_index = 531
    ui_realtime.notify_ui_state_changed(
        organization_id=principal.organization_id,
        client_id=base_client_id + target_index,
    )

    for index, subscription in enumerate(subscriptions):
        claims = ui_realtime.verify_ui_realtime_capability(subscription["capability"])
        generation = ui_realtime.wait_for_ui_change(
            claims=claims,
            after=subscription["generation"],
            timeout=0,
        )
        if index == target_index:
            assert generation > subscription["generation"]
        else:
            assert generation == subscription["generation"]
