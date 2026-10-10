"""HTTP boundary for the retained status/display/system ClientFlow domains."""
from __future__ import annotations

from typing import Any


from fastapi import APIRouter, Header, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..db import engine
from ..display_control import (
    apply_display_command_completion,
    apply_display_command_failure,
    reconcile_display_configuration,
    reconcile_kiosk_lockdown,
)
from ..calendar_control import (
    build_display_calendar_delivery_with_etag,
    display_calendar_delivery_etag,
)
from ..system_control import apply_status_power_observation, apply_system_command_completion
from ..models import Client
from ..ephemeral_presence import touch_presence
from ..realtime_wakeup import current_generation, wait_for_change_async
from ..ui_realtime import notify_ui_state_changed
from ..shared_domain import (
    claim_shared_command,
    complete_shared_command,
    fail_shared_command,
    renew_shared_command,
    require_shared_agent_context,
    require_shared_agent_token,
    upsert_shared_status,
    verify_shared_agent_wake_token,
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
    status_report: StatusBody | None = None


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


def _client_identity_payload(
    client_or_session: Client | Session,
    client_id: int | None = None,
) -> dict[str, Any]:
    """Build the public client identity without forcing a second hot-path read.

    The status heartbeat passes the Client already validated by
    ``require_shared_agent_context``.  The optional ``client_id`` form keeps the
    pre-existing helper contract for focused callers/tests and performs the
    legacy lookup only when that form is explicitly used.
    """
    client: Any
    if client_id is None:
        client = client_or_session
    else:
        client = client_or_session.get(Client, client_id)
        if client is None:
            raise RuntimeError("Status credential refererer til en manglende klient")

    return {
        "schema_version": 1,
        "client_id": int(client.id),
        "name": str(client.name or "").strip(),
        "locality": str(client.locality).strip() if client.locality else None,
    }


def _apply_status_in_session(
    session: Session,
    *,
    domain: str,
    client_id: int,
    body: StatusBody,
    authorization_context: Any,
) -> dict[str, Any]:
    """Apply one canonical status report using an already-validated request context."""
    credential = authorization_context.credential
    client = authorization_context.client
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
        active_command_cache: dict[str, Any] = {}
        reconcile_display_configuration(
            session,
            client_id=client_id,
            agent_version=body.agent_version,
            status_payload=body.status_payload,
            active_command_cache=active_command_cache,
        )
        reconcile_kiosk_lockdown(
            session,
            client_id=client_id,
            agent_version=body.agent_version,
            status_payload=body.status_payload,
            client=client,
            active_command_cache=active_command_cache,
        )
    elif domain == "status":
        apply_status_power_observation(
            session,
            client_id=client_id,
            status_payload=body.status_payload,
            boot_id=body.boot_id,
            client=client,
        )
    client_identity = _client_identity_payload(client) if domain == "status" else None
    response = {
        "ok": True,
        "client_id": row.client_id,
        "domain": row.domain,
        "observed_state": row.observed_state,
        "reported_at": row.reported_at,
    }
    touch_presence(domain, client_id, at=row.reported_at)
    if client_identity is not None:
        response["client_identity"] = client_identity
    return response


def _status(domain: str, client_id: int, body: StatusBody, authorization: str | None):
    with Session(engine) as session:
        authorization_context = require_shared_agent_context(
            session,
            authorization,
            client_id=client_id,
            domain=domain,
        )
        response = _apply_status_in_session(
            session,
            domain=domain,
            client_id=client_id,
            body=body,
            authorization_context=authorization_context,
        )
        organization_id = getattr(authorization_context.client, "organization_id", None)
        session.commit()
        notify_ui_state_changed(organization_id=organization_id, client_id=client_id)
        return response


def _claim(domain: str, client_id: int, body: ClaimBody, authorization: str | None):
    with Session(engine) as session:
        status_organization_id = None
        if body.status_report is None:
            credential = require_shared_agent_token(
                session, authorization, client_id=client_id, domain=domain
            )
        else:
            authorization_context = require_shared_agent_context(
                session,
                authorization,
                client_id=client_id,
                domain=domain,
            )
            credential = authorization_context.credential
            status_organization_id = getattr(authorization_context.client, "organization_id", None)
            _apply_status_in_session(
                session,
                domain=domain,
                client_id=client_id,
                body=body.status_report,
                authorization_context=authorization_context,
            )
        payload = claim_shared_command(session, credential=credential, lease_seconds=body.lease_seconds)
        if body.status_report is not None:
            # Explicit ACK is required for rolling compatibility. An older backend
            # may ignore the unknown status_report field; the client then falls back
            # to the historical standalone heartbeat instead of assuming success.
            payload["status_reported"] = True
        session.commit()
        if body.status_report is not None:
            notify_ui_state_changed(organization_id=status_organization_id, client_id=client_id)
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
        elif domain == "display":
            apply_display_command_completion(session, client_id=client_id, command_id=command_id)
        client = session.get(Client, client_id)
        organization_id = getattr(client, "organization_id", None) if client is not None else None
        session.commit()
        notify_ui_state_changed(organization_id=organization_id, client_id=client_id)
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
        if domain == "display" and payload.get("status") == "failed":
            apply_display_command_failure(
                session, client_id=client_id, command_id=command_id, error_message=body.error_message
            )
        client = session.get(Client, client_id)
        organization_id = getattr(client, "organization_id", None) if client is not None else None
        session.commit()
        notify_ui_state_changed(organization_id=organization_id, client_id=client_id)
        return payload


@router.get("/display-agent/clients/{client_id}/calendar")
def display_calendar(
    client_id: int,
    authorization: str | None = Header(default=None),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    with Session(engine) as session:
        authorization_context = require_shared_agent_context(
            session,
            authorization,
            client_id=client_id,
            domain="display",
        )
        cache_headers = {"Cache-Control": "private, no-cache"}
        if if_none_match:
            current_etag = display_calendar_delivery_etag(
                session,
                client_id=client_id,
                authorized_client=authorization_context.client,
            )
            if current_etag and current_etag in {part.strip() for part in if_none_match.split(",")}:
                return Response(
                    status_code=304,
                    headers={**cache_headers, "ETag": current_etag},
                )

        payload, etag = build_display_calendar_delivery_with_etag(
            session,
            client_id=client_id,
            authorized_client=authorization_context.client,
        )
        headers = dict(cache_headers)
        if etag:
            headers["ETag"] = etag
        return JSONResponse(content=payload, headers=headers)




async def _wake_wait(domain: str, client_id: int, after: int, timeout_seconds: int, authorization: str | None):
    verify_shared_agent_wake_token(authorization, client_id=client_id, domain=domain)
    generation = await wait_for_change_async(domain, client_id, after, timeout_seconds)
    return {
        "ok": True,
        "generation": generation,
        "changed": generation > int(after),
    }


async def _wake_ws(websocket: WebSocket, *, domain: str, client_id: int) -> None:
    authorization = websocket.headers.get("authorization")
    try:
        verify_shared_agent_wake_token(authorization, client_id=client_id, domain=domain)
    except Exception:
        await websocket.close(code=4401, reason="Ugyldigt command wake-token")
        return
    await websocket.accept()
    generation = current_generation(domain, client_id)
    await websocket.send_json({"type": "wake_ready", "generation": generation})
    try:
        while True:
            next_generation = await wait_for_change_async(
                domain, client_id, generation, 45.0
            )
            if next_generation > generation:
                generation = next_generation
                await websocket.send_json({
                    "type": "command_available",
                    "generation": generation,
                })
            else:
                await websocket.send_json({"type": "keepalive", "generation": generation})
    except (WebSocketDisconnect, RuntimeError):
        return


@router.get("/display-agent/clients/{client_id}/commands/wait")
async def display_wait(
    client_id: int,
    after: int = Query(default=0, ge=0),
    timeout_seconds: int = Query(default=25, ge=1, le=30),
    authorization: str | None = Header(default=None),
):
    return await _wake_wait("display", client_id, after, timeout_seconds, authorization)


@router.get("/system-agent/clients/{client_id}/commands/wait")
async def system_wait(
    client_id: int,
    after: int = Query(default=0, ge=0),
    timeout_seconds: int = Query(default=25, ge=1, le=30),
    authorization: str | None = Header(default=None),
):
    return await _wake_wait("system", client_id, after, timeout_seconds, authorization)


@router.websocket("/display-agent/clients/{client_id}/commands/wake/ws")
async def display_wake_ws(websocket: WebSocket, client_id: int):
    await _wake_ws(websocket, domain="display", client_id=client_id)


@router.websocket("/system-agent/clients/{client_id}/commands/wake/ws")
async def system_wake_ws(websocket: WebSocket, client_id: int):
    await _wake_ws(websocket, domain="system", client_id=client_id)


def _agent_presence(domain: str, client_id: int, authorization: str | None):
    # Signed domain tokens are verified locally. Durable status/auth remains
    # database-authoritative on full checkpoints and token renewal.
    verify_shared_agent_wake_token(authorization, client_id=client_id, domain=domain)
    observed_at = touch_presence(domain, client_id)
    return {"ok": True, "client_id": client_id, "domain": domain, "observed_at": observed_at}


@router.post("/status-agent/clients/{client_id}/presence")
def status_agent_presence(client_id: int, authorization: str | None = Header(default=None)):
    return _agent_presence("status", client_id, authorization)


@router.post("/display-agent/clients/{client_id}/presence")
def display_agent_presence(client_id: int, authorization: str | None = Header(default=None)):
    return _agent_presence("display", client_id, authorization)


@router.post("/system-agent/clients/{client_id}/presence")
def system_agent_presence(client_id: int, authorization: str | None = Header(default=None)):
    return _agent_presence("system", client_id, authorization)


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
