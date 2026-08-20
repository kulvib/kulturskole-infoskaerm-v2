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


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


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
        occurred_at=_utc_naive(occurred_at),
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


def authorize_activation(
    session: Session,
    *,
    deployment_id: str,
    credential_id: str | None = None,
    event_id: str | None = None,
    occurred_at: datetime | None = None,
) -> ClientFlowDeployment:
    """Atomic STAGED -> ACTIVATING gate used immediately before local mutation.

    This function intentionally performs no network or filesystem work.  The
    updater must receive a successful transaction result before it mutates the
    active runtime.  Once ACTIVATING is committed, cancellation is forbidden.
    """
    deployment = deployment_for_update(session, deployment_id)
    existing = _idempotent_event(
        session,
        event_id=event_id,
        deployment_id=deployment_id,
        credential_id=credential_id,
        event_type="activation_started",
    )
    if existing is not None:
        return deployment
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
        credential_id=credential_id,
        occurred_at=occurred_at,
        event_id=event_id,
    )
    return deployment


def _idempotent_event(
    session: Session,
    *,
    event_id: str | None,
    deployment_id: str,
    credential_id: str | None,
    event_type: str,
) -> ClientFlowDeploymentEvent | None:
    if not event_id:
        return None
    normalized = str(uuid.UUID(event_id))
    existing = session.get(ClientFlowDeploymentEvent, normalized)
    if existing is None:
        return None
    if (
        existing.deployment_id != deployment_id
        or existing.credential_id != credential_id
        or existing.event_type != event_type
    ):
        raise ClientFlowDeploymentConflict("Event-id er allerede brugt til en anden deployment-event")
    return existing


def report_updater_event(
    session: Session,
    *,
    deployment_id: str,
    credential_id: str,
    event_id: str,
    event_type: str,
    payload: Mapping[str, object] | None = None,
    occurred_at: datetime | None = None,
) -> tuple[ClientFlowDeployment, ClientFlowDeploymentEvent, bool]:
    """Apply one authenticated updater observation through backend-owned transitions."""
    deployment = deployment_for_update(session, deployment_id)
    existing = _idempotent_event(
        session,
        event_id=event_id,
        deployment_id=deployment_id,
        credential_id=credential_id,
        event_type=event_type,
    )
    if existing is not None:
        return deployment, existing, True

    data = dict(payload or {})
    transitions: dict[str, dict[str, str]] = {
        "download_started": {"authorized": "downloading"},
        "bundle_verified": {"downloading": "verified"},
        "staged": {"verified": "staged"},
        "health_check_started": {"activating": "health_check"},
        "succeeded": {"health_check": "succeeded"},
        "failed": {
            "authorized": "failed",
            "downloading": "failed",
            "verified": "failed",
            "staged": "failed",
        },
        "rollback_started": {"activating": "rolling_back", "health_check": "rolling_back"},
        "rolled_back": {"rolling_back": "rolled_back"},
        "recovery_failed": {
            "activating": "recovery_failed",
            "health_check": "recovery_failed",
            "rolling_back": "recovery_failed",
        },
    }
    if event_type not in transitions:
        if event_type != "observation":
            raise ClientFlowDeploymentConflict(f"Ukendt updater event_type {event_type!r}")
    else:
        next_state = transitions[event_type].get(deployment.state)
        if next_state is None:
            raise ClientFlowDeploymentConflict(
                f"Event {event_type!r} er ikke gyldig fra state {deployment.state!r}"
            )
        if event_type == "succeeded":
            observed_release_id = str(data.get("observed_release_id") or "").strip()
            try:
                observed_sequence = int(data.get("observed_release_sequence"))
            except (TypeError, ValueError) as exc:
                raise ClientFlowDeploymentConflict("succeeded kræver observed_release_sequence") from exc
            if (
                observed_release_id != deployment.target_release_id
                or observed_sequence != deployment.target_release_sequence
            ):
                raise ClientFlowDeploymentConflict(
                    "succeeded observation matcher ikke den autoriserede target release"
                )
            deployment.observed_release_id = observed_release_id
            deployment.observed_release_sequence = observed_sequence
            previous = str(data.get("observed_previous_release_id") or "").strip() or None
            deployment.observed_previous_release_id = previous
        if event_type in {"failed", "recovery_failed"}:
            deployment.failure_code = str(data.get("failure_code") or "update_failed")[:100]
            deployment.failure_message = str(data.get("failure_message") or "")[:4000] or None
        deployment.state = next_state
        deployment.state_updated_at = utcnow()
        if next_state in CLIENTFLOW_DEPLOYMENT_TERMINAL_STATES:
            deployment.completed_at = deployment.state_updated_at
        session.add(deployment)

    event = append_event(
        session,
        deployment_id=deployment.id,
        event_type=event_type,
        payload=data,
        credential_id=credential_id,
        occurred_at=occurred_at,
        event_id=event_id,
    )
    session.flush()
    return deployment, event, False


def is_terminal_state(state: str) -> bool:
    return state in CLIENTFLOW_DEPLOYMENT_TERMINAL_STATES
