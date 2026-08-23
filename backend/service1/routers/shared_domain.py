"""HTTP boundary for the retained status/display/system ClientFlow domains."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db import engine
from ..display_control import reconcile_display_configuration
from ..calendar_control import build_display_calendar_delivery
from ..system_control import apply_system_command_completion
from ..shared_domain import (
    claim_shared_command,
    complete_shared_command,
    fail_shared_command,
    renew_shared_command,
    require_shared_agent_token,
    upsert_shared_status,
)

router = APIRouter(tags=["shared-domain-agent"])


class StatusBody(BaseModel):
    schema_version: int = Field(ge=1)
    observed_state: str = Field(min_length=1, max_length=80)
    status_payload: dict[str, Any] = Field(default_factory=dict)
    agent_version: str | None = Field(default=None, max_length=80)
    boot_id: str | None = Field(default=None, max_length=128)


class ClaimBody(BaseModel):
    lease_seconds: int = Field(default=60, ge=10, le=300)


class RenewBody(BaseModel):
    claim_token: str = Field(min_length=20, max_length=512)
    lease_seconds: int = Field(default=60, ge=10, le=300)


class CompleteBody(BaseModel):
    claim_token: str = Field(min_length=20, max_length=512)
    result: dict[str, Any] = Field(default_factory=dict)


class FailBody(BaseModel):
    claim_token: str = Field(min_length=20, max_length=512)
    error_code: str = Field(min_length=1, max_length=120)
    error_message: str = Field(default="", max_length=2000)
    retryable: bool = False


def _status(domain: str, client_id: int, body: StatusBody, authorization: str | None):
    with Session(engine) as session:
        credential = require_shared_agent_token(
            session,
            authorization,
            client_id=client_id,
            domain=domain,
        )
        row = upsert_shared_status(
            session,
            credential=credential,
            schema_version=body.schema_version,
            observed_state=body.observed_state,
            status_payload=body.status_payload,
            agent_version=body.agent_version,
            boot_id=body.boot_id,
        )
        if domain == "display":
            reconcile_display_configuration(
                session,
                client_id=client_id,
                agent_version=body.agent_version,
                status_payload=body.status_payload,
            )
        session.commit()
        return {
            "ok": True,
            "client_id": row.client_id,
            "domain": row.domain,
            "observed_state": row.observed_state,
            "reported_at": row.reported_at,
        }


def _claim(domain: str, client_id: int, body: ClaimBody, authorization: str | None):
    with Session(engine) as session:
        credential = require_shared_agent_token(session, authorization, client_id=client_id, domain=domain)
        payload = claim_shared_command(session, credential=credential, lease_seconds=body.lease_seconds)
        session.commit()
        return payload


def _renew(domain: str, client_id: int, command_id: str, body: RenewBody, authorization: str | None):
    with Session(engine) as session:
        credential = require_shared_agent_token(session, authorization, client_id=client_id, domain=domain)
        payload = renew_shared_command(
            session,
            credential=credential,
            command_id=command_id,
            claim_token=body.claim_token,
            lease_seconds=body.lease_seconds,
        )
        session.commit()
        return payload


def _complete(domain: str, client_id: int, command_id: str, body: CompleteBody, authorization: str | None):
    with Session(engine) as session:
        credential = require_shared_agent_token(session, authorization, client_id=client_id, domain=domain)
        payload = complete_shared_command(
            session,
            credential=credential,
            command_id=command_id,
            claim_token=body.claim_token,
            result=body.result,
        )
        if domain == "system":
            apply_system_command_completion(session, client_id=client_id, command_id=command_id)
        session.commit()
        return payload


def _fail(domain: str, client_id: int, command_id: str, body: FailBody, authorization: str | None):
    with Session(engine) as session:
        credential = require_shared_agent_token(session, authorization, client_id=client_id, domain=domain)
        payload = fail_shared_command(
            session,
            credential=credential,
            command_id=command_id,
            claim_token=body.claim_token,
            error_code=body.error_code,
            error_message=body.error_message,
            retryable=body.retryable,
        )
        session.commit()
        return payload


@router.get("/display-agent/clients/{client_id}/calendar")
def display_calendar(client_id: int, authorization: str | None = Header(default=None)):
    with Session(engine) as session:
        require_shared_agent_token(
            session,
            authorization,
            client_id=client_id,
            domain="display",
        )
        return build_display_calendar_delivery(session, client_id=client_id)


@router.put("/status-agent/clients/{client_id}/status")
def status_agent_status(client_id: int, body: StatusBody, authorization: str | None = Header(default=None)):
    return _status("status", client_id, body, authorization)


@router.put("/display-agent/clients/{client_id}/status")
def display_agent_status(client_id: int, body: StatusBody, authorization: str | None = Header(default=None)):
    return _status("display", client_id, body, authorization)


@router.put("/system-agent/clients/{client_id}/status")
def system_agent_status(client_id: int, body: StatusBody, authorization: str | None = Header(default=None)):
    return _status("system", client_id, body, authorization)


@router.post("/display-agent/clients/{client_id}/commands/claim")
def display_claim(client_id: int, body: ClaimBody, authorization: str | None = Header(default=None)):
    return _claim("display", client_id, body, authorization)


@router.post("/system-agent/clients/{client_id}/commands/claim")
def system_claim(client_id: int, body: ClaimBody, authorization: str | None = Header(default=None)):
    return _claim("system", client_id, body, authorization)


@router.post("/display-agent/clients/{client_id}/commands/{command_id}/renew")
def display_renew(client_id: int, command_id: str, body: RenewBody, authorization: str | None = Header(default=None)):
    return _renew("display", client_id, command_id, body, authorization)


@router.post("/system-agent/clients/{client_id}/commands/{command_id}/renew")
def system_renew(client_id: int, command_id: str, body: RenewBody, authorization: str | None = Header(default=None)):
    return _renew("system", client_id, command_id, body, authorization)


@router.post("/display-agent/clients/{client_id}/commands/{command_id}/complete")
def display_complete(client_id: int, command_id: str, body: CompleteBody, authorization: str | None = Header(default=None)):
    return _complete("display", client_id, command_id, body, authorization)


@router.post("/system-agent/clients/{client_id}/commands/{command_id}/complete")
def system_complete(client_id: int, command_id: str, body: CompleteBody, authorization: str | None = Header(default=None)):
    return _complete("system", client_id, command_id, body, authorization)


@router.post("/display-agent/clients/{client_id}/commands/{command_id}/fail")
def display_fail(client_id: int, command_id: str, body: FailBody, authorization: str | None = Header(default=None)):
    return _fail("display", client_id, command_id, body, authorization)


@router.post("/system-agent/clients/{client_id}/commands/{command_id}/fail")
def system_fail(client_id: int, command_id: str, body: FailBody, authorization: str | None = Header(default=None)):
    return _fail("system", client_id, command_id, body, authorization)
