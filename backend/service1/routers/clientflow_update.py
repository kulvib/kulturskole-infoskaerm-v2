"""Stable updater authentication, reprovisioning and deployment reporting API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlmodel import Session

from ..audit import add_audit_log
from ..clientflow_artifact_auth import (
    ClientFlowArtifactAuthorizationError,
    authenticate_artifact_request,
    issue_artifact_access_token,
)
from ..clientflow_release_artifacts import (
    ClientFlowReleaseArtifactError,
    open_artifact_matches_deployment,
    verify_artifact_matches_deployment,
)
from ..auth import get_current_superadmin_user
from ..clientflow_deployments import (
    ClientFlowDeploymentConflict,
    ClientFlowDeploymentNotFound,
    active_deployment,
    authorize_activation,
    report_updater_event,
)
from ..clientflow_update_auth import (
    ClientFlowUpdateAuthError,
    UPDATE_ACCESS_TOKEN_AUDIENCE,
    UPDATE_ACCESS_TOKEN_ISSUER,
    UPDATE_TOKEN_AUDIENCE,
    active_update_credential,
    authenticate_update_request,
    canonical_update_public_key,
    consume_provisioning_token,
    consume_replay,
    create_provisioning_token,
    http_auth_error,
    issue_update_access_token,
    normalize_scopes,
    rotate_update_credential,
    utcnow,
    verify_client_assertion,
    verify_dpop_proof,
    verify_new_key_proof,
)
from ..clientflow_update_models import ClientFlowDeployment, ClientFlowUpdateCredential
from ..db import get_session
from ..models import Client
from ..rate_limit import enforce_request_rate_limit
from .clientflow_deployments import ClientFlowDeploymentRead

router = APIRouter(tags=["clientflow-update"])
CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


class UpdateTokenRequest(BaseModel):
    client_assertion_type: str = PydanticField(min_length=1, max_length=200)
    client_assertion: str = PydanticField(min_length=40, max_length=16_384)
    scope: Optional[str] = PydanticField(default=None, max_length=500)


class UpdateTokenResponse(BaseModel):
    access_token: str
    token_type: str = "DPoP"
    expires_in: int
    scope: str


class UpdateProvisioningTokenRead(BaseModel):
    code: str
    expires_at: datetime
    purpose: str


class UpdateProvisionRequest(BaseModel):
    code: str = PydanticField(min_length=24, max_length=200)
    public_key_pem: str = PydanticField(min_length=80, max_length=4096)


class UpdateCredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    client_id: int
    key_id: str
    algorithm: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    rotated_from_credential_id: Optional[str] = None
    token_audience: str = UPDATE_TOKEN_AUDIENCE
    access_token_issuer: str = UPDATE_ACCESS_TOKEN_ISSUER
    access_token_audience: str = UPDATE_ACCESS_TOKEN_AUDIENCE


class UpdateCredentialRotateRequest(BaseModel):
    public_key_pem: str = PydanticField(min_length=80, max_length=4096)
    new_key_proof: str = PydanticField(min_length=40, max_length=16_384)


class UpdateDeploymentEventRequest(BaseModel):
    event_id: str = PydanticField(min_length=36, max_length=36)
    event_type: str = PydanticField(min_length=1, max_length=80)
    occurred_at: Optional[datetime] = None
    payload: dict[str, Any] = PydanticField(default_factory=dict)


class UpdateActivationRequest(BaseModel):
    event_id: str = PydanticField(min_length=36, max_length=36)
    occurred_at: Optional[datetime] = None


class UpdateDeploymentReportResponse(BaseModel):
    deployment: ClientFlowDeploymentRead
    replayed: bool = False


class UpdateArtifactAuthorizationResponse(BaseModel):
    access_token: str
    token_type: str = "DPoP"
    expires_in: int
    release_id: str
    bundle_sha256: str
    bundle_size: int
    artifact_url: str


def _client_or_404(session: Session, client_id: int) -> Client:
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _require_active_approved_client(client: Client) -> None:
    if getattr(client, "deleted_at", None) is not None or str(getattr(client, "status", "")) != "approved":
        raise HTTPException(status_code=409, detail="Update credential kræver en aktiv godkendt klient")


def _credential_read(row: ClientFlowUpdateCredential) -> UpdateCredentialRead:
    return UpdateCredentialRead(
        id=row.id,
        client_id=row.client_id,
        key_id=row.key_id,
        algorithm=row.algorithm,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        rotated_from_credential_id=row.rotated_from_credential_id,
    )


def _principal(session: Session, request: Request, *, scope: str):
    try:
        principal = authenticate_update_request(session, request=request, required_scope=scope)
        # Replay consumption and last_used_at belong to authentication, not to
        # the later business transaction.  A rejected event must still consume
        # the one-time DPoP proof.
        session.commit()
        return principal
    except ClientFlowUpdateAuthError as exc:
        session.rollback()
        raise http_auth_error(exc) from exc


def _deployment_for_principal(
    session: Session,
    *,
    deployment_id: str,
    client_id: int,
) -> ClientFlowDeployment:
    row = session.get(ClientFlowDeployment, deployment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ClientFlow deployment blev ikke fundet")
    if int(row.client_id) != int(client_id):
        raise HTTPException(status_code=404, detail="ClientFlow deployment blev ikke fundet")
    return row


@router.post("/clientflow-update/token", response_model=UpdateTokenResponse)
def issue_clientflow_update_token(
    body: UpdateTokenRequest,
    request: Request,
    dpop: Optional[str] = Header(default=None, alias="DPoP"),
    session: Session = Depends(get_session),
):
    enforce_request_rate_limit(
        request,
        bucket="clientflow-update-token",
        max_attempts=120,
        window_seconds=60,
        detail="For mange ClientFlow update-auth forsøg",
    )
    if body.client_assertion_type != CLIENT_ASSERTION_TYPE:
        raise HTTPException(status_code=400, detail="client_assertion_type er ugyldig")
    if not dpop:
        raise HTTPException(status_code=401, detail="DPoP proof mangler")
    try:
        scopes = normalize_scopes(body.scope)
        credential, client, assertion_jti, assertion_exp = verify_client_assertion(
            session,
            assertion=body.client_assertion,
        )
        consume_replay(
            session,
            credential_id=credential.id,
            kind="client_assertion",
            jti=assertion_jti,
            expires_at=assertion_exp,
        )
        dpop_thumbprint = verify_dpop_proof(
            session,
            request=request,
            proof=dpop,
            credential=credential,
            access_token=None,
        )
        token, ttl = issue_update_access_token(
            credential=credential,
            client=client,
            scopes=scopes,
            dpop_thumbprint=dpop_thumbprint,
        )
        credential.last_used_at = utcnow()
        session.add(credential)
        session.commit()
        return UpdateTokenResponse(
            access_token=token,
            expires_in=ttl,
            scope=" ".join(sorted(scopes)),
        )
    except ClientFlowUpdateAuthError as exc:
        session.rollback()
        raise http_auth_error(exc) from exc


@router.post(
    "/clients/{client_id}/clientflow-update-credential/provisioning-token",
    response_model=UpdateProvisioningTokenRead,
)
def create_clientflow_update_provisioning_token(
    client_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    client = _client_or_404(session, client_id)
    _require_active_approved_client(client)
    try:
        token, code = create_provisioning_token(
            session,
            client=client,
            created_by_user_id=getattr(user, "id", None),
        )
    except ClientFlowUpdateAuthError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    add_audit_log(
        session,
        action="clientflow_update_provisioning_authorized",
        request=request,
        actor=user,
        target_organization_id=client.organization_id,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        severity="critical" if token.purpose == "recovery" else "warning",
        is_critical=token.purpose == "recovery",
        details={"client_id": client.id, "purpose": token.purpose, "token_id": token.id},
    )
    session.commit()
    return UpdateProvisioningTokenRead(code=code, expires_at=token.expires_at, purpose=token.purpose)


@router.post("/clients/{client_id}/clientflow-update-credential/revoke", response_model=UpdateCredentialRead)
def revoke_clientflow_update_credential(
    client_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(get_current_superadmin_user),
):
    client = _client_or_404(session, client_id)
    credential = active_update_credential(session, client_id=client_id, for_update=True)
    if credential is None:
        raise HTTPException(status_code=404, detail="Aktiv ClientFlow update credential blev ikke fundet")
    credential.revoked_at = utcnow()
    session.add(credential)
    add_audit_log(
        session,
        action="clientflow_update_credential_revoked",
        request=request,
        actor=user,
        target_organization_id=client.organization_id,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        severity="critical",
        is_critical=True,
        details={
            "client_id": client.id,
            "credential_id": credential.id,
            "key_id": credential.key_id,
        },
    )
    session.commit()
    session.refresh(credential)
    return _credential_read(credential)


@router.post("/clientflow-update/provision", response_model=UpdateCredentialRead)
def provision_clientflow_update_credential(
    body: UpdateProvisionRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    enforce_request_rate_limit(
        request,
        bucket="clientflow-update-provision",
        max_attempts=20,
        window_seconds=60,
        detail="For mange ClientFlow update-provisioning forsøg",
    )
    try:
        credential, token, client = consume_provisioning_token(
            session,
            code=body.code,
            public_key_pem=body.public_key_pem,
        )
        add_audit_log(
            session,
            action="clientflow_update_credential_provisioned",
            request=request,
            target_organization_id=client.organization_id,
            entity_type="client",
            entity_id=client.id,
            entity_label=client.name,
            severity="critical" if token.purpose == "recovery" else "warning",
            is_critical=token.purpose == "recovery",
            details={
                "client_id": client.id,
                "credential_id": credential.id,
                "key_id": credential.key_id,
                "purpose": token.purpose,
            },
        )
        session.commit()
        session.refresh(credential)
        return _credential_read(credential)
    except ClientFlowUpdateAuthError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/clientflow-update/credential/rotate", response_model=UpdateCredentialRead)
def rotate_clientflow_update_credential(
    body: UpdateCredentialRotateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    principal = _principal(session, request, scope="credential:rotate")
    try:
        canonical_pem, _key_id, _jwk, _jkt = canonical_update_public_key(body.public_key_pem)
        verify_new_key_proof(
            request=request,
            proof=body.new_key_proof,
            new_public_key_pem=canonical_pem,
            current_credential_id=principal.credential.id,
        )
        successor = rotate_update_credential(
            session,
            current=principal.credential,
            new_public_key_pem=canonical_pem,
        )
        add_audit_log(
            session,
            action="clientflow_update_credential_rotated",
            request=request,
            target_organization_id=principal.client.organization_id,
            entity_type="client",
            entity_id=principal.client.id,
            entity_label=principal.client.name,
            severity="warning",
            details={
                "client_id": principal.client.id,
                "old_credential_id": principal.credential.id,
                "new_credential_id": successor.id,
                "new_key_id": successor.key_id,
            },
        )
        session.commit()
        session.refresh(successor)
        return _credential_read(successor)
    except ClientFlowUpdateAuthError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/clientflow-update/deployments/{deployment_id}/artifact-authorization",
    response_model=UpdateArtifactAuthorizationResponse,
)
def authorize_clientflow_artifact_download(
    deployment_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    principal = _principal(session, request, scope="artifact:authorize")
    deployment = _deployment_for_principal(
        session,
        deployment_id=deployment_id,
        client_id=int(principal.client.id),
    )
    release = {
        "release_id": deployment.target_release_id,
        "version": deployment.target_version,
        "release_sequence": deployment.target_release_sequence,
    }
    try:
        verify_artifact_matches_deployment(
            release,
            deployment_release_id=deployment.target_release_id,
            bundle_sha256=deployment.bundle_sha256,
            bundle_size=deployment.bundle_size,
            approval_reference=deployment.release_approval_reference,
        )
        token, ttl = issue_artifact_access_token(principal=principal, deployment=deployment)
    except ClientFlowReleaseArtifactError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ClientFlowArtifactAuthorizationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return UpdateArtifactAuthorizationResponse(
        access_token=token,
        expires_in=ttl,
        release_id=deployment.target_release_id,
        bundle_sha256=deployment.bundle_sha256,
        bundle_size=deployment.bundle_size,
        artifact_url=f"/api/clientflow/release-artifacts/{deployment.target_release_id}",
    )


@router.get("/clientflow/release-artifacts/{release_id}")
def download_clientflow_release_artifact(
    release_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        principal = authenticate_artifact_request(
            session,
            request=request,
            release_id=release_id,
        )
        # DPoP replay consumption and credential last_used belong to auth and
        # remain consumed even if the separately published artifact is missing.
        session.commit()
        deployment = principal.deployment
        artifact, artifact_handle = open_artifact_matches_deployment(
            {
                "release_id": deployment.target_release_id,
                "version": deployment.target_version,
                "release_sequence": deployment.target_release_sequence,
            },
            deployment_release_id=deployment.target_release_id,
            bundle_sha256=deployment.bundle_sha256,
            bundle_size=deployment.bundle_size,
            approval_reference=deployment.release_approval_reference,
        )
    except ClientFlowArtifactAuthorizationError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except ClientFlowReleaseArtifactError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def stream_verified_artifact():
        try:
            while chunk := artifact_handle.read(1024 * 1024):
                yield chunk
        finally:
            artifact_handle.close()

    return StreamingResponse(
        stream_verified_artifact(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Disposition": f'attachment; filename="{artifact.release_id}.tar"',
            "Content-Length": str(artifact.bundle_size),
            "ETag": f'"sha256-{artifact.bundle_sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/clientflow-update/deployments/active", response_model=Optional[ClientFlowDeploymentRead])
def get_updater_active_deployment(
    request: Request,
    session: Session = Depends(get_session),
):
    principal = _principal(session, request, scope="deployment:read")
    return active_deployment(session, client_id=int(principal.client.id))


@router.post(
    "/clientflow-update/deployments/{deployment_id}/events",
    response_model=UpdateDeploymentReportResponse,
)
def report_clientflow_update_event(
    deployment_id: str,
    body: UpdateDeploymentEventRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    principal = _principal(session, request, scope="deployment:report")
    _deployment_for_principal(
        session,
        deployment_id=deployment_id,
        client_id=int(principal.client.id),
    )
    try:
        deployment, _event, replayed = report_updater_event(
            session,
            deployment_id=deployment_id,
            credential_id=principal.credential.id,
            event_id=str(uuid.UUID(body.event_id)),
            event_type=body.event_type,
            occurred_at=body.occurred_at,
            payload=body.payload,
        )
        session.commit()
        session.refresh(deployment)
        return UpdateDeploymentReportResponse(deployment=ClientFlowDeploymentRead.model_validate(deployment), replayed=replayed)
    except (ValueError, ClientFlowDeploymentConflict, ClientFlowDeploymentNotFound) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/clientflow-update/deployments/{deployment_id}/activation-start",
    response_model=ClientFlowDeploymentRead,
)
def start_clientflow_update_activation(
    deployment_id: str,
    body: UpdateActivationRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    principal = _principal(session, request, scope="deployment:report")
    _deployment_for_principal(
        session,
        deployment_id=deployment_id,
        client_id=int(principal.client.id),
    )
    try:
        deployment = authorize_activation(
            session,
            deployment_id=deployment_id,
            credential_id=principal.credential.id,
            event_id=str(uuid.UUID(body.event_id)),
            occurred_at=body.occurred_at,
        )
        session.commit()
        session.refresh(deployment)
        return deployment
    except (ValueError, ClientFlowDeploymentConflict, ClientFlowDeploymentNotFound) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
