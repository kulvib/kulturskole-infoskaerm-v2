"""Compatibility token boundary for Livestream and retained shared domains.

Terminal and Remote Desktop own isolated auth routes. The installed 1.2.0
status/display/system agents still use ``/api/client-auth/token`` and their
shared ``client_domain_credential`` rows, so this boundary preserves exactly
those domains while keeping Terminal/RD excluded.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..auth import verify_password
from ..client_domain_models import ClientDomainCredential, ClientDomainStatus
from ..models import Client, utcnow

from ..db import engine
from ..shared_domain import SHARED_DOMAINS, issue_shared_domain_token_response
from ..livestream_v2 import (
    CLIENT_TOKEN_TTL_SECONDS,
    TOKEN_ISSUER,
    authenticate_credential,
    create_client_token,
)

router = APIRouter(tags=["client-auth-compat"])


class ClientTokenBody(BaseModel):
    client_id: int = Field(gt=0)
    credential_id: str = Field(min_length=1, max_length=64)
    domain: str = Field(min_length=1, max_length=64)
    client_secret: str = Field(min_length=32, max_length=512)


class ApprovalReadinessBody(BaseModel):
    client_id: int = Field(gt=0)
    credential_id: str = Field(min_length=1, max_length=64)
    client_secret: str = Field(min_length=32, max_length=512)
    preclaim_boot_id: str = Field(min_length=36, max_length=64)
    boot_id: str = Field(min_length=36, max_length=64)
    kiosk_session_ready: bool
    preactivation_gui_ready: bool
    package_manager_healthy: bool
    post_reboot_reboot_required: bool


@router.post("/client-auth/approval-readiness")
def publish_approval_readiness(body: ApprovalReadinessBody):
    """Publish the authenticated post-reboot readiness proof for fresh install.

    This endpoint deliberately does not mint a runtime token. Pending clients
    remain unable to authenticate to Status/Display/System until a human
    administrator approves them. The status credential is used only to bind
    this one lifecycle proof to the exact claimed client.
    """
    if body.preclaim_boot_id == body.boot_id:
        raise HTTPException(status_code=409, detail="Approval-readiness kræver en gennemført reboot")
    if not body.kiosk_session_ready or not body.preactivation_gui_ready or not body.package_manager_healthy:
        raise HTTPException(status_code=409, detail="Klienten har ikke bestået post-reboot readiness")
    if body.post_reboot_reboot_required:
        raise HTTPException(status_code=409, detail="Ubuntu kræver endnu en reboot før klienten kan godkendes")

    with Session(engine) as session:
        client = session.get(Client, body.client_id)
        credential = session.get(ClientDomainCredential, body.credential_id)
        if (
            client is None
            or client.deleted_at is not None
            or str(client.status or "").lower() != "pending"
            or credential is None
            or credential.client_id != body.client_id
            or credential.domain != "status"
            or credential.revoked_at is not None
        ):
            raise HTTPException(status_code=401, detail="Ugyldigt pending readiness-credential")
        try:
            verified = verify_password(body.client_secret, credential.secret_hash)
        except Exception:
            verified = False
        if not verified:
            raise HTTPException(status_code=401, detail="Ugyldigt pending readiness-credential")

        now = utcnow()
        credential.last_used_at = now
        readiness = {
            "schema_version": 1,
            "preclaim_boot_id": body.preclaim_boot_id,
            "boot_id": body.boot_id,
            "kiosk_session_ready": True,
            "preactivation_gui_ready": True,
            "package_manager_healthy": True,
            "post_reboot_reboot_required": False,
            "approval_ready_at": now.isoformat(),
        }
        status_row = session.exec(
            select(ClientDomainStatus).where(
                ClientDomainStatus.client_id == body.client_id,
                ClientDomainStatus.domain == "status",
            )
        ).one_or_none()
        if status_row is None:
            status_row = ClientDomainStatus(
                id=str(uuid.uuid4()),
                client_id=body.client_id,
                domain="status",
                schema_version=1,
                observed_state="approval_ready",
                status_payload=readiness,
                agent_version="preactivation-bootstrap",
                boot_id=body.boot_id,
                credential_id=credential.id,
                reported_at=now,
            )
        else:
            status_row.schema_version = 1
            status_row.observed_state = "approval_ready"
            status_row.status_payload = readiness
            status_row.agent_version = "preactivation-bootstrap"
            status_row.boot_id = body.boot_id
            status_row.credential_id = credential.id
            status_row.reported_at = now
        session.add(credential)
        session.add(status_row)
        session.commit()
        return {
            "client_id": body.client_id,
            "status": client.status,
            "approval_ready": True,
            "approval_ready_at": now,
            "boot_id": body.boot_id,
        }


@router.post("/client-auth/token")
def client_token_compat(body: ClientTokenBody):
    if body.domain == "livestream":
        with Session(engine) as session:
            credential = authenticate_credential(
                session,
                client_id=body.client_id,
                credential_id=body.credential_id,
                domain=body.domain,
                client_secret=body.client_secret,
            )
            session.commit()
            token, expires_at = create_client_token(credential)
            return {
                "access_token": token,
                "token_type": "bearer",
                "expires_in": CLIENT_TOKEN_TTL_SECONDS,
                "client_id": credential.client_id,
                "credential_id": credential.id,
                "domain": credential.domain,
                "audience": f"clientflow-domain:{credential.domain}",
                "scope": f"clientflow:{credential.domain}",
                "issuer": TOKEN_ISSUER,
                "token_version": credential.token_version,
                "expires_at": expires_at,
            }

    if body.domain in SHARED_DOMAINS:
        with Session(engine) as session:
            payload = issue_shared_domain_token_response(
                session,
                client_id=body.client_id,
                credential_id=body.credential_id,
                domain=body.domain,
                client_secret=body.client_secret,
            )
            session.commit()
            return payload

    raise HTTPException(status_code=404, detail="Domæne-endpoint ikke fundet")
