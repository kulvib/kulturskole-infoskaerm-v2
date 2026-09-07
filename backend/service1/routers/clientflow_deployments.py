"""Superadmin control plane for first-class ClientFlow deployments.

Updater authentication/event endpoints are intentionally added in the next
bootstrap-auth block.  This router establishes only backend authorization,
history, cancellation and immutable release snapshots.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..audit import add_audit_log
from ..auth import get_current_superadmin_user
from ..client_presence import load_client_presence
from ..clientflow_deployments import (
    ClientFlowDeploymentConflict,
    ClientFlowDeploymentNotFound,
    active_deployment,
    cancel_deployment,
    create_authorized_deployment,
)
from ..clientflow_releases import (
    ClientFlowArtifactUnavailable,
    ClientFlowCatalogError,
    compare_versions,
    deployment_release_snapshot,
    load_catalog,
    resolve_release,
    validate_release_compatibility,
)
from ..clientflow_update_models import ClientFlowDeployment
from ..db import get_session
from ..models import AuditLog, Client
from ..system_control import active_system_command, lock_system_client

router = APIRouter(tags=["clientflow-deployments"])


class ClientFlowDeploymentCreate(BaseModel):
    target_version: str = PydanticField(..., min_length=1, max_length=40)
    confirm_downgrade: bool = False
    reason: Optional[str] = PydanticField(default=None, max_length=500)
    pre_first_activation_repair: bool = False


class ClientFlowDeploymentCancel(BaseModel):
    reason: Optional[str] = PydanticField(default=None, max_length=500)


class ClientFlowDeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: int
    target_release_id: str
    target_version: str
    target_release_sequence: int
    bundle_sha256: str
    bundle_size: int
    release_approval_reference: str
    release_candidate_sha256: Optional[str] = None
    source_commit: Optional[str] = None
    allow_downgrade: bool
    reason: Optional[str] = None
    requested_by_user_id: Optional[int] = None
    requested_at: datetime
    state: str
    state_updated_at: datetime
    completed_at: Optional[datetime] = None
    observed_previous_release_id: Optional[str] = None
    observed_release_id: Optional[str] = None
    observed_release_sequence: Optional[int] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None


def _client_or_404(session: Session, client_id: int) -> Client:
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _require_deployable_client(session: Session, client: Client) -> None:
    if getattr(client, "deleted_at", None) is not None or str(getattr(client, "status", "")) != "approved":
        raise HTTPException(status_code=409, detail="ClientFlow deployment kræver en aktiv godkendt klient")
    if client.id is not None:
        active = active_system_command(session, int(client.id))
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=f"ClientFlow deployment kan ikke startes under aktiv System-handling '{active.command_type}'",
            )




def _canonical_runtime_version(session: Session, client: Client) -> str:
    presence = load_client_presence(session, client)
    status = presence.status
    version = str(status.agent_version or "").strip().lstrip("vV")
    if not status.is_online or not version:
        raise HTTPException(
            status_code=409,
            detail="ClientFlow deployment kræver frisk canonical Status-version fra en online klient",
        )
    return version


def _fresh_install_claim_binding(session: Session, client: Client) -> dict[str, object]:
    if client.id is None:
        raise HTTPException(status_code=409, detail="Klienten mangler canonical identity")
    row = session.exec(
        select(AuditLog)
        .where(
            AuditLog.action == "client_enrolled",
            AuditLog.entity_type == "client",
            AuditLog.entity_id == int(client.id),
        )
        .order_by(AuditLog.created_at.desc())
    ).first()
    details = dict(getattr(row, "details", None) or {}) if row is not None else {}
    required = {
        "release_id": details.get("fresh_install_release_id"),
        "version": details.get("fresh_install_version"),
        "release_sequence": details.get("fresh_install_release_sequence"),
        "bundle_sha256": details.get("fresh_install_bundle_sha256"),
        "bundle_size": details.get("fresh_install_bundle_size"),
        "approval_reference": details.get("fresh_install_approval_reference"),
        "candidate_sha256": details.get("fresh_install_candidate_sha256"),
        "source_commit": details.get("fresh_install_source_commit"),
    }
    try:
        required["release_sequence"] = int(required["release_sequence"])
        required["bundle_size"] = int(required["bundle_size"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Klienten mangler en gyldig server-side fresh-install claim-binding") from exc
    release_id = str(required["release_id"] or "").strip()
    version = str(required["version"] or "").strip().lstrip("vV")
    bundle_sha256 = str(required["bundle_sha256"] or "").strip().lower()
    approval_reference = str(required["approval_reference"] or "").strip()
    candidate_sha256 = str(required["candidate_sha256"] or "").strip().lower()
    source_commit = str(required["source_commit"] or "").strip().lower()
    if (
        not release_id
        or not version
        or release_id != f"clientflow-{version}-seq-{required['release_sequence']}"
        or len(bundle_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in bundle_sha256)
        or required["bundle_size"] <= 0
        or not approval_reference
        or len(candidate_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in candidate_sha256)
        or len(source_commit) not in {40, 64}
        or any(ch not in "0123456789abcdef" for ch in source_commit)
    ):
        raise HTTPException(status_code=409, detail="Klienten mangler en gyldig server-side fresh-install claim-binding")
    return required


def _pre_first_activation_repair_current(session: Session, client: Client) -> dict[str, object]:
    presence = load_client_presence(session, client)
    status = presence.status
    if status.is_online:
        raise HTTPException(
            status_code=409,
            detail="Pre-first-activation repair er kun tilladt uden en aktiv canonical Status-runtime",
        )
    return _fresh_install_claim_binding(session, client)

def _require_pre_first_activation_repair_target(
    release: dict[str, object],
    binding: dict[str, object],
    *,
    reason: str | None,
) -> None:
    target_version = str(release.get("version") or "").strip()
    current_version = str(binding.get("version") or "").strip()
    try:
        target_sequence = int(release.get("release_sequence"))
        original_sequence = int(binding.get("release_sequence"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Repair release identity er ugyldig") from exc
    if target_sequence <= original_sequence or compare_versions(target_version, current_version) <= 0:
        raise HTTPException(
            status_code=409,
            detail="Pre-first-activation repair kræver en strengt nyere approved release end den oprindelige claim-binding",
        )
    if not str(reason or "").strip():
        raise HTTPException(status_code=400, detail="Pre-first-activation repair kræver en begrundelse")


def _require_version_change(target_version: str, current_version: str) -> None:
    if compare_versions(target_version, current_version) == 0:
        raise HTTPException(
            status_code=409,
            detail=f"ClientFlow {target_version} er allerede installeret; same-version deployment er ikke tilladt",
        )


def _deployment_or_404(session: Session, deployment_id: str) -> ClientFlowDeployment:
    row = session.get(ClientFlowDeployment, deployment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ClientFlow deployment blev ikke fundet")
    return row


@router.post("/clients/{client_id}/clientflow-deployments", response_model=ClientFlowDeploymentRead, status_code=201)
def create_clientflow_deployment(
    client_id: int,
    body: ClientFlowDeploymentCreate,
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    client = _client_or_404(session, client_id)
    _require_deployable_client(session, client)
    requested_version = str(body.target_version or "").strip()
    if requested_version.lower() == "latest":
        raise HTTPException(status_code=400, detail="ClientFlow deployment kræver en konkret katalogversion; 'latest' er ikke tilladt")
    repair_binding = None
    if body.pre_first_activation_repair:
        repair_binding = _pre_first_activation_repair_current(session, client)
        current_version = str(repair_binding["version"])
    else:
        current_version = _canonical_runtime_version(session, client)
    try:
        catalog = load_catalog()
        release = resolve_release(requested_version)
        validate_release_compatibility(
            release,
            current_version=current_version,
            ubuntu_version=client.ubuntu_version,
        )
    except ClientFlowCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target_version = str(release["version"])
    _require_version_change(target_version, current_version)
    if repair_binding is not None:
        _require_pre_first_activation_repair_target(release, repair_binding, reason=body.reason)
    latest_version = str(catalog["latest_stable"])
    is_downgrade = bool(current_version and compare_versions(target_version, current_version) < 0)
    is_non_latest_without_current = bool(not current_version and target_version != latest_version)
    requires_downgrade = is_downgrade or is_non_latest_without_current
    reason = str(body.reason or "").strip() or None

    if requires_downgrade:
        if release.get("rollback_allowed") is not True:
            raise HTTPException(status_code=400, detail=f"ClientFlow {target_version} er ikke godkendt som rollback-version")
        if not body.confirm_downgrade:
            raise HTTPException(status_code=400, detail="Nedgradering kræver eksplicit bekræftelse")
        if reason is None:
            raise HTTPException(status_code=400, detail="Nedgradering kræver en begrundelse")

    try:
        artifact = deployment_release_snapshot(release)
    except ClientFlowArtifactUnavailable as exc:
        # This is backend release-publication state, not bad admin input.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        # Serialize canonical System commands and ClientFlow deployments on the
        # same client row, then re-check after acquiring the lock. This closes
        # the race where both producers could pass their preliminary guard.
        lock_system_client(session, int(client.id))
        _require_deployable_client(session, client)
        deployment = create_authorized_deployment(
            session,
            client_id=int(client.id),
            requested_by_user_id=getattr(user, "id", None),
            target_release_id=artifact["target_release_id"],
            target_version=target_version,
            target_release_sequence=int(release["release_sequence"]),
            bundle_sha256=artifact["bundle_sha256"],
            bundle_size=artifact["bundle_size"],
            release_approval_reference=artifact["release_approval_reference"],
            release_candidate_sha256=artifact["release_candidate_sha256"],
            source_commit=artifact["source_commit"],
            allow_downgrade=requires_downgrade,
            reason=reason,
        )
        add_audit_log(
            session,
            action="clientflow_deployment_authorized",
            request=request,
            actor=user,
            target_organization_id=client.organization_id,
            entity_type="clientflow_deployment",
            entity_id=client.id,
            entity_label=f"{client.name} → {target_version}",
            severity="critical" if requires_downgrade else "warning",
            is_critical=requires_downgrade,
            details={
                "client_id": client.id,
                "deployment_id": deployment.id,
                "target_release_id": deployment.target_release_id,
                "target_release_sequence": deployment.target_release_sequence,
                "bundle_sha256": deployment.bundle_sha256,
                "bundle_size": deployment.bundle_size,
                "release_approval_reference": deployment.release_approval_reference,
                "allow_downgrade": deployment.allow_downgrade,
                "pre_first_activation_repair": repair_binding is not None,
                "repair_from_release_id": repair_binding.get("release_id") if repair_binding else None,
                "repair_from_release_sequence": repair_binding.get("release_sequence") if repair_binding else None,
                "reason": reason,
            },
        )
        session.commit()
        session.refresh(deployment)
        return deployment
    except ClientFlowDeploymentConflict as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Klienten har allerede en aktiv ClientFlow-deployment") from exc


@router.get("/clients/{client_id}/clientflow-deployments", response_model=list[ClientFlowDeploymentRead])
def list_clientflow_deployments(
    client_id: int,
    session: Session = Depends(get_session),
    _user=Depends(get_current_superadmin_user),
):
    _client_or_404(session, client_id)
    return session.exec(
        select(ClientFlowDeployment)
        .where(ClientFlowDeployment.client_id == client_id)
        .order_by(ClientFlowDeployment.requested_at.desc())
    ).all()


@router.get("/clients/{client_id}/clientflow-deployments/active", response_model=Optional[ClientFlowDeploymentRead])
def get_active_clientflow_deployment(
    client_id: int,
    session: Session = Depends(get_session),
    _user=Depends(get_current_superadmin_user),
):
    _client_or_404(session, client_id)
    return active_deployment(session, client_id=client_id)


@router.post("/clientflow-deployments/{deployment_id}/cancel", response_model=ClientFlowDeploymentRead)
def cancel_clientflow_deployment(
    deployment_id: str,
    body: ClientFlowDeploymentCancel,
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    current = _deployment_or_404(session, deployment_id)
    client = _client_or_404(session, current.client_id)
    try:
        deployment = cancel_deployment(session, deployment_id=deployment_id, reason=body.reason)
        add_audit_log(
            session,
            action="clientflow_deployment_cancelled",
            request=request,
            actor=user,
            target_organization_id=client.organization_id,
            entity_type="clientflow_deployment",
            entity_id=client.id,
            entity_label=f"{client.name} → {deployment.target_version}",
            severity="warning",
            details={"client_id": client.id, "deployment_id": deployment.id, "reason": body.reason},
        )
        session.commit()
        session.refresh(deployment)
        return deployment
    except (ClientFlowDeploymentConflict, ClientFlowDeploymentNotFound) as exc:
        session.rollback()
        status_code = 404 if isinstance(exc, ClientFlowDeploymentNotFound) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
