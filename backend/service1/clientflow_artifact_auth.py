"""Deployment-bound, DPoP-bound authorization for exact ClientFlow artifact bytes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

import jwt
from fastapi import Request
from sqlmodel import Session

from .auth import ALGORITHM as PLATFORM_JWT_ALGORITHM, SECRET_KEY
from .clientflow_update_auth import (
    ClientFlowUpdateAuthError,
    UpdatePrincipal,
    require_update_client_active,
    utcnow,
    verify_dpop_proof,
)
from .clientflow_update_models import ClientFlowDeployment, ClientFlowUpdateCredential

ARTIFACT_ACCESS_TOKEN_TYP = "clientflow-artifact-access+jwt"
ARTIFACT_ACCESS_TOKEN_AUDIENCE = "urn:planiq:clientflow-update:artifact"
ARTIFACT_ACCESS_TOKEN_ISSUER = "planiq-clientflow-update"
ARTIFACT_ACCESS_TOKEN_TTL_SECONDS = 120
ARTIFACT_DOWNLOADABLE_STATES = frozenset({"authorized", "downloading", "verified", "staged"})


class ClientFlowArtifactAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArtifactPrincipal:
    client_id: int
    credential: ClientFlowUpdateCredential
    deployment: ClientFlowDeployment
    token: str
    dpop_thumbprint: str
    claims: dict[str, Any]


def _require_downloadable(deployment: ClientFlowDeployment) -> None:
    if deployment.completed_at is not None or deployment.state not in ARTIFACT_DOWNLOADABLE_STATES:
        raise ClientFlowArtifactAuthorizationError(
            "Artifact-download er kun tilladt før deploymentens activation-start"
        )


def issue_artifact_access_token(
    *,
    principal: UpdatePrincipal,
    deployment: ClientFlowDeployment,
) -> tuple[str, int]:
    if int(deployment.client_id) != int(principal.client.id):
        raise ClientFlowArtifactAuthorizationError("Deployment matcher ikke update identity")
    _require_downloadable(deployment)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ARTIFACT_ACCESS_TOKEN_TTL_SECONDS)
    claims = {
        "iss": ARTIFACT_ACCESS_TOKEN_ISSUER,
        "sub": f"clientflow-artifact:{deployment.id}",
        "aud": ARTIFACT_ACCESS_TOKEN_AUDIENCE,
        "principal": "clientflow-artifact",
        "client_id": int(principal.client.id),
        "credential_id": principal.credential.id,
        "deployment_id": deployment.id,
        "release_id": deployment.target_release_id,
        "bundle_sha256": deployment.bundle_sha256,
        "bundle_size": int(deployment.bundle_size),
        "approval_reference": deployment.release_approval_reference,
        "cnf": {"jkt": principal.dpop_thumbprint},
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(
        claims,
        SECRET_KEY,
        algorithm=PLATFORM_JWT_ALGORITHM,
        headers={"typ": ARTIFACT_ACCESS_TOKEN_TYP},
    )
    return token, ARTIFACT_ACCESS_TOKEN_TTL_SECONDS


def authenticate_artifact_request(
    session: Session,
    *,
    request: Request,
    release_id: str,
) -> ArtifactPrincipal:
    authorization = str(request.headers.get("authorization") or "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "dpop" or not token:
        raise ClientFlowArtifactAuthorizationError("Artifact endpoint kræver Authorization: DPoP")
    proof = str(request.headers.get("dpop") or "").strip()
    if not proof:
        raise ClientFlowArtifactAuthorizationError("Artifact endpoint mangler DPoP proof")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise ClientFlowArtifactAuthorizationError("Artifact access-token er ugyldigt") from exc
    if header.get("typ") != ARTIFACT_ACCESS_TOKEN_TYP or header.get("alg") != PLATFORM_JWT_ALGORITHM:
        raise ClientFlowArtifactAuthorizationError("Artifact access-token har forkert JWT type/algoritme")
    try:
        claims = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[PLATFORM_JWT_ALGORITHM],
            audience=ARTIFACT_ACCESS_TOKEN_AUDIENCE,
            issuer=ARTIFACT_ACCESS_TOKEN_ISSUER,
            options={
                "require": [
                    "iss", "sub", "aud", "principal", "client_id", "credential_id",
                    "deployment_id", "release_id", "bundle_sha256", "bundle_size",
                    "approval_reference", "cnf", "iat", "nbf", "exp", "jti",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise ClientFlowArtifactAuthorizationError("Artifact access-token kunne ikke valideres") from exc
    if claims.get("principal") != "clientflow-artifact":
        raise ClientFlowArtifactAuthorizationError("Artifact access-token har forkert principal")
    if str(claims.get("release_id") or "") != str(release_id):
        raise ClientFlowArtifactAuthorizationError("Artifact access-token matcher ikke requested release")

    credential_id = str(claims.get("credential_id") or "")
    credential = session.get(ClientFlowUpdateCredential, credential_id)
    if credential is None or credential.revoked_at is not None:
        raise ClientFlowArtifactAuthorizationError("Update credential er revoked eller mangler")
    try:
        client = require_update_client_active(session, credential)
    except ClientFlowUpdateAuthError as exc:
        raise ClientFlowArtifactAuthorizationError(str(exc)) from exc
    if int(claims.get("client_id") or 0) != int(client.id):
        raise ClientFlowArtifactAuthorizationError("Artifact access-token client_id matcher ikke credential")

    deployment_id = str(claims.get("deployment_id") or "")
    deployment = session.get(ClientFlowDeployment, deployment_id)
    if deployment is None or int(deployment.client_id) != int(client.id):
        raise ClientFlowArtifactAuthorizationError("Artifact deployment blev ikke fundet for update identity")
    _require_downloadable(deployment)
    if claims.get("sub") != f"clientflow-artifact:{deployment.id}":
        raise ClientFlowArtifactAuthorizationError("Artifact access-token subject matcher ikke deployment")
    expected = (
        deployment.target_release_id,
        deployment.bundle_sha256,
        int(deployment.bundle_size),
        deployment.release_approval_reference,
    )
    try:
        claimed_bundle_size = int(claims.get("bundle_size") or 0)
    except (TypeError, ValueError) as exc:
        raise ClientFlowArtifactAuthorizationError("Artifact access-token bundle_size er ugyldig") from exc
    actual = (
        str(claims.get("release_id") or ""),
        str(claims.get("bundle_sha256") or "").lower(),
        claimed_bundle_size,
        str(claims.get("approval_reference") or ""),
    )
    if actual != expected:
        raise ClientFlowArtifactAuthorizationError("Artifact access-token matcher ikke deployment snapshot")
    cnf = claims.get("cnf")
    if not isinstance(cnf, dict) or not str(cnf.get("jkt") or ""):
        raise ClientFlowArtifactAuthorizationError("Artifact access-token mangler DPoP binding")
    try:
        thumbprint = verify_dpop_proof(
            session,
            request=request,
            proof=proof,
            credential=credential,
            access_token=token,
            expected_thumbprint=str(cnf["jkt"]),
        )
    except ClientFlowUpdateAuthError as exc:
        raise ClientFlowArtifactAuthorizationError(str(exc)) from exc
    credential.last_used_at = utcnow()
    session.add(credential)
    return ArtifactPrincipal(
        client_id=int(client.id),
        credential=credential,
        deployment=deployment,
        token=token,
        dpop_thumbprint=thumbprint,
        claims=claims,
    )
