"""State-machine primitives for first-class ClientFlow deployments."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping
import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .clientflow_update_models import (
    CLIENTFLOW_DEPLOYMENT_CANCELLABLE_STATES,
    CLIENTFLOW_DEPLOYMENT_TERMINAL_STATES,
    ClientFlowDeployment,
    ClientFlowDeploymentEvent,
)


class ClientFlowDeploymentConflict(RuntimeError):
    pass


class ClientFlowDeploymentNotFound(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def active_deployment(session: Session, *, client_id: int, for_update: bool = False) -> ClientFlowDeployment | None:
    statement = select(ClientFlowDeployment).where(
        ClientFlowDeployment.client_id == client_id,
        ClientFlowDeployment.completed_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def deployment_for_update(session: Session, deployment_id: str) -> ClientFlowDeployment:
    row = session.exec(
        select(ClientFlowDeployment)
        .where(ClientFlowDeployment.id == deployment_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise ClientFlowDeploymentNotFound(deployment_id)
    return row


def append_event(
    session: Session,
    *,
    deployment_id: str,
    event_type: str,
    payload: Mapping[str, object] | None = None,
    credential_id: str | None = None,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> ClientFlowDeploymentEvent:
    event = ClientFlowDeploymentEvent(
        id=str(uuid.UUID(event_id)) if event_id else str(uuid.uuid4()),
        deployment_id=deployment_id,
        credential_id=credential_id,
        event_type=str(event_type),
        occurred_at=occurred_at,
        received_at=utcnow(),
        payload=dict(payload or {}),
    )
    session.add(event)
    return event


def create_authorized_deployment(
    session: Session,
    *,
    client_id: int,
    requested_by_user_id: int | None,
    target_release_id: str,
    target_version: str,
    target_release_sequence: int,
    bundle_sha256: str,
    bundle_size: int,
    release_approval_reference: str,
    allow_downgrade: bool,
    reason: str | None,
    release_candidate_sha256: str | None = None,
    source_commit: str | None = None,
) -> ClientFlowDeployment:
    if active_deployment(session, client_id=client_id, for_update=True) is not None:
        raise ClientFlowDeploymentConflict("Klienten har allerede en aktiv ClientFlow-deployment")

    now = utcnow()
    deployment = ClientFlowDeployment(
        id=str(uuid.uuid4()),
        client_id=client_id,
        target_release_id=target_release_id,
        target_version=target_version,
        target_release_sequence=target_release_sequence,
        bundle_sha256=bundle_sha256,
        bundle_size=bundle_size,
        release_approval_reference=release_approval_reference,
        release_candidate_sha256=release_candidate_sha256,
        source_commit=source_commit,
        allow_downgrade=allow_downgrade,
        reason=reason,
        requested_by_user_id=requested_by_user_id,
        requested_at=now,
        state="authorized",
        state_updated_at=now,
        completed_at=None,
    )
    session.add(deployment)
    append_event(
        session,
        deployment_id=deployment.id,
        event_type="authorized",
        payload={
            "target_release_id": target_release_id,
            "target_version": target_version,
            "target_release_sequence": target_release_sequence,
            "bundle_sha256": bundle_sha256,
            "bundle_size": bundle_size,
            "release_approval_reference": release_approval_reference,
            "allow_downgrade": allow_downgrade,
        },
    )
    try:
        session.flush()
    except IntegrityError as exc:
        # The partial unique index is the final authority for concurrent admin
        # requests that race after the application-level row check.
        raise ClientFlowDeploymentConflict(
            "Klienten har allerede en aktiv ClientFlow-deployment"
        ) from exc
    return deployment


def cancel_deployment(session: Session, *, deployment_id: str, reason: str | None = None) -> ClientFlowDeployment:
    deployment = deployment_for_update(session, deployment_id)
    if deployment.state not in CLIENTFLOW_DEPLOYMENT_CANCELLABLE_STATES:
        raise ClientFlowDeploymentConflict(
            f"Deployment kan ikke annulleres fra state {deployment.state!r}"
        )
    now = utcnow()
    previous_state = deployment.state
    deployment.state = "cancelled"
    deployment.state_updated_at = now
    deployment.completed_at = now
    session.add(deployment)
    append_event(
        session,
        deployment_id=deployment.id,
        event_type="cancelled",
        payload={"previous_state": previous_state, "reason": reason},
    )
    return deployment


def authorize_activation(session: Session, *, deployment_id: str) -> ClientFlowDeployment:
    """Atomic STAGED -> ACTIVATING gate used immediately before local mutation.

    This function intentionally performs no network or filesystem work.  The
    updater must receive a successful transaction result before it mutates the
    active runtime.  Once ACTIVATING is committed, cancellation is forbidden.
    """
    deployment = deployment_for_update(session, deployment_id)
    if deployment.state != "staged" or deployment.completed_at is not None:
        raise ClientFlowDeploymentConflict(
            f"Deployment er ikke klar til activation (state={deployment.state!r})"
        )
    deployment.state = "activating"
    deployment.state_updated_at = utcnow()
    session.add(deployment)
    append_event(
        session,
        deployment_id=deployment.id,
        event_type="activation_started",
        payload={"previous_state": "staged"},
    )
    return deployment


def is_terminal_state(state: str) -> bool:
    return state in CLIENTFLOW_DEPLOYMENT_TERMINAL_STATES
