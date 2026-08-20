from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from service1.clientflow_deployments import (
    ClientFlowDeploymentConflict,
    authorize_activation,
    cancel_deployment,
    create_authorized_deployment,
)
from service1.clientflow_update_models import ClientFlowDeployment
from service1.models import Client, User


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
    deployment.state_updated_at = datetime.utcnow()
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
