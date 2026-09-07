"""Compatibility token boundary for Livestream and retained shared domains.

Terminal and Remote Desktop own isolated auth routes. The installed 1.2.0
status/display/system agents still use ``/api/client-auth/token`` and their
shared ``client_domain_credential`` rows, so this boundary preserves exactly
those domains while keeping Terminal/RD excluded.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

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
