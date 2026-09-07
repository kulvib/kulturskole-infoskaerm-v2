import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from service1.clientflow_deployments import (
    ClientFlowDeploymentConflict,
    authorize_activation,
    cancel_deployment,
    create_authorized_deployment,
    report_updater_event,
    utcnow,
)
from service1.clientflow_update_models import ClientFlowDeployment, ClientFlowUpdateCredential
from service1.models import Client, User


TEST_UPDATE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAzU6003WsShJbh/Yk3H4tAwXd4ep+A128YEJSAYemC68=
-----END PUBLIC KEY-----
"""


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as value:
        user = User(
            username="deployment-admin",
            email="deployment-admin@example.invalid",
            hashed_password="hashed",
            role="superadmin",
            is_active=True,
            must_change_password=False,
        )
        client = Client(name="deployment-client", status="approved")
        value.add(user)
        value.add(client)
        value.commit()
        value.refresh(user)
        value.refresh(client)
        yield value, client, user




def _credential(value: Session, client: Client) -> ClientFlowUpdateCredential:
    row = ClientFlowUpdateCredential(
        id=str(uuid.uuid4()),
        client_id=int(client.id),
        key_id=uuid.uuid4().hex,
        public_key_pem=TEST_UPDATE_PUBLIC_KEY_PEM,
        algorithm="Ed25519",
        created_at=utcnow(),
    )
    value.add(row)
    value.commit()
    return row

def _create(value: Session, client: Client, user: User):
    return create_authorized_deployment(
        value,
        client_id=int(client.id),
        requested_by_user_id=int(user.id),
        target_release_id="clientflow-1.3.0-seq-1300",
        target_version="1.3.0",
        target_release_sequence=1300,
        bundle_sha256="a" * 64,
        bundle_size=123456,
        release_approval_reference="approval-1300",
        allow_downgrade=False,
        reason=None,
    )


def test_one_active_deployment_per_client_and_cancel_releases_slot(session):
    value, client, user = session
    first = _create(value, client, user)
    value.commit()

    with pytest.raises(ClientFlowDeploymentConflict):
        _create(value, client, user)
    value.rollback()

    cancelled = cancel_deployment(value, deployment_id=first.id, reason="admin cancelled")
    value.commit()
    assert cancelled.state == "cancelled"
    assert cancelled.completed_at is not None

    second = _create(value, client, user)
    value.commit()
    assert second.state == "authorized"


def test_activation_gate_is_atomic_and_cannot_be_cancelled_after_activation(session):
    value, client, user = session
    deployment = _create(value, client, user)
    value.commit()
    deployment.state = "staged"
    deployment.state_updated_at = utcnow()
    value.add(deployment)
    value.commit()

    activated = authorize_activation(value, deployment_id=deployment.id)
    value.commit()
    assert activated.state == "activating"

    with pytest.raises(ClientFlowDeploymentConflict):
        cancel_deployment(value, deployment_id=deployment.id)


def test_terminal_state_requires_completed_at_at_database_boundary(session):
    value, client, user = session
    deployment = _create(value, client, user)
    value.commit()
    deployment.state = "succeeded"
    deployment.completed_at = None
    value.add(deployment)
    with pytest.raises(IntegrityError):
        value.commit()

def test_authenticated_updater_events_follow_backend_owned_state_machine(session):
    value, client, user = session
    credential = _credential(value, client)
    deployment = _create(value, client, user)
    value.commit()

    for event_type, expected_state in (
        ("download_started", "downloading"),
        ("bundle_verified", "verified"),
        ("staged", "staged"),
    ):
        event_id = str(uuid.uuid4())
        deployment, event, replayed = report_updater_event(
            value,
            deployment_id=deployment.id,
            credential_id=credential.id,
            event_id=event_id,
            event_type=event_type,
        )
        value.commit()
        assert not replayed
        assert event.id == event_id
        assert deployment.state == expected_state

    activation_event_id = str(uuid.uuid4())
    deployment = authorize_activation(
        value,
        deployment_id=deployment.id,
        credential_id=credential.id,
        event_id=activation_event_id,
    )
    value.commit()
    assert deployment.state == "activating"

    deployment, _event, _replayed = report_updater_event(
        value,
        deployment_id=deployment.id,
        credential_id=credential.id,
        event_id=str(uuid.uuid4()),
        event_type="health_check_started",
    )
    value.commit()
    assert deployment.state == "health_check"

    success_event_id = str(uuid.uuid4())
    success_payload = {
        "observed_release_id": deployment.target_release_id,
        "observed_release_sequence": deployment.target_release_sequence,
        "observed_previous_release_id": "clientflow-1.2.0-seq-1200",
    }
    deployment, event, replayed = report_updater_event(
        value,
        deployment_id=deployment.id,
        credential_id=credential.id,
        event_id=success_event_id,
        event_type="succeeded",
        payload=success_payload,
    )
    value.commit()
    assert not replayed
    assert deployment.state == "succeeded"
    assert deployment.completed_at is not None
    assert deployment.observed_release_id == deployment.target_release_id
    assert deployment.observed_release_sequence == deployment.target_release_sequence

    replayed_deployment, replayed_event, replayed = report_updater_event(
        value,
        deployment_id=deployment.id,
        credential_id=credential.id,
        event_id=success_event_id,
        event_type="succeeded",
        payload=success_payload,
    )
    assert replayed
    assert replayed_deployment.id == deployment.id
    assert replayed_event.id == event.id


def test_succeeded_event_cannot_claim_a_different_release(session):
    value, client, user = session
    credential = _credential(value, client)
    deployment = _create(value, client, user)
    value.commit()
    deployment.state = "health_check"
    deployment.state_updated_at = utcnow()
    value.add(deployment)
    value.commit()

    with pytest.raises(ClientFlowDeploymentConflict, match="matcher ikke"):
        report_updater_event(
            value,
            deployment_id=deployment.id,
            credential_id=credential.id,
            event_id=str(uuid.uuid4()),
            event_type="succeeded",
            payload={
                "observed_release_id": "attacker-release",
                "observed_release_sequence": deployment.target_release_sequence,
            },
        )
    value.rollback()
    stored = value.get(ClientFlowDeployment, deployment.id)
    assert stored.state == "health_check"
    assert stored.completed_at is None


def test_event_id_reuse_with_different_meaning_is_rejected(session):
    value, client, user = session
    credential = _credential(value, client)
    deployment = _create(value, client, user)
    value.commit()
    event_id = str(uuid.uuid4())

    report_updater_event(
        value,
        deployment_id=deployment.id,
        credential_id=credential.id,
        event_id=event_id,
        event_type="download_started",
    )
    value.commit()

    with pytest.raises(ClientFlowDeploymentConflict, match="Event-id"):
        report_updater_event(
            value,
            deployment_id=deployment.id,
            credential_id=credential.id,
            event_id=event_id,
            event_type="observation",
        )

def test_updater_event_occurrence_time_is_normalized_to_utc_naive(session):
    value, client, user = session
    credential = _credential(value, client)
    deployment = _create(value, client, user)
    value.commit()
    event_id = str(uuid.uuid4())
    local_time = datetime(2026, 8, 20, 9, 30, tzinfo=timezone(timedelta(hours=2)))

    _deployment, event, _replayed = report_updater_event(
        value,
        deployment_id=deployment.id,
        credential_id=credential.id,
        event_id=event_id,
        event_type="observation",
        occurred_at=local_time,
    )
    value.commit()
    assert event.occurred_at == datetime(2026, 8, 20, 7, 30)
    assert event.occurred_at.tzinfo is None

