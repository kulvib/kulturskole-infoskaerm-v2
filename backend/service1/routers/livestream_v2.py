"""HTTP boundary for the isolated ClientFlow 1.2 Livestream control plane."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from ..auth import get_current_user_or_client
from ..db import engine
from ..models import Client
from ..livestream_v2 import (
    CLIENT_TOKEN_TTL_SECONDS,
    MAX_HLS_FILE_BYTES,
    TOKEN_ISSUER,
    VIEWER_HEARTBEAT_SECONDS,
    VIEWER_LEASE_SECONDS,
    VIEWER_STOP_GRACE_SECONDS,
    active_viewer_count,
    authenticate_credential,
    claim_command,
    complete_command,
    create_client_token,
    current_generation,
    explicit_stop_latched,
    fail_command,
    generation_started,
    generation_stopped,
    maybe_recover_stale_media,
    reconcile_stopping_generation_from_agent_status,
    renew_command,
    request_restart,
    request_start,
    request_stop,
    require_agent_token,
    update_agent_status,
    viewer_heartbeat,
    viewer_leave,
    write_hls_file,
)
from .livestream_media import require_hls_access

router = APIRouter()




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
    error_code: str = Field(min_length=1, max_length=128)
    error_message: str = Field(default="", max_length=2000)
    retryable: bool = False


class AgentStatusBody(BaseModel):
    schema_version: int
    observed_state: str = Field(min_length=1, max_length=64)
    status_payload: dict[str, Any] = Field(default_factory=dict)
    agent_version: str = Field(min_length=1, max_length=64)
    boot_id: Optional[str] = Field(default=None, max_length=128)


class StoppedBody(BaseModel):
    error_code: Optional[str] = Field(default=None, max_length=128)


class ViewerHeartbeatBody(BaseModel):
    viewer_id: str = Field(min_length=1, max_length=120)
    source: Optional[str] = Field(default=None, max_length=120)


class ViewerLeaveBody(BaseModel):
    viewer_id: str = Field(min_length=1, max_length=120)
    source: Optional[str] = Field(default=None, max_length=120)


class BrowserCommandBody(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    source: Optional[str] = Field(default=None, max_length=120)


def _require_active_platform_client(client_id: int) -> None:
    """Livestream v2 lifecycle is owned by an approved platform Client."""
    with Session(engine) as session:
        client = session.get(Client, int(client_id))
        if (
            client is None
            or str(getattr(client, "status", "") or "").lower() != "approved"
            or getattr(client, "deleted_at", None) is not None
        ):
            raise HTTPException(status_code=403, detail="Livestream-klienten er ikke aktiv")


def _require_browser_control_access(user: object, client_id: str) -> None:
    """Authorize browser control without granting HLS file-write privileges."""
    # First enforce the ordinary client/org read boundary. The legacy
    # require_hls_access(write=True) boundary is intentionally stricter because
    # it protects segment upload/cleanup and only permits the client agent or a
    # superadmin. Browser start/stop is a control operation instead: the active
    # UI contract permits superadmin, same-org admin and same-org bruger.
    require_hls_access(user, client_id)
    if (
        getattr(user, "is_superadmin", False)
        or getattr(user, "is_admin", False)
        or getattr(user, "role", None) == "bruger"
    ):
        return
    raise HTTPException(status_code=403, detail="Du har ikke adgang til at styre Livestream")


def _no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


async def _read_bounded_body(request: Request, *, maximum: int) -> bytes:
    raw_length = str(request.headers.get("content-length") or "").strip()
    if raw_length:
        try:
            declared = int(raw_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Ugyldig Content-Length") from exc
        if declared < 0:
            raise HTTPException(status_code=400, detail="Ugyldig Content-Length")
        if declared > maximum:
            raise HTTPException(status_code=413, detail="Livestreamfil er for stor")

    payload = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        if len(payload) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="Livestreamfil er for stor")
        payload.extend(chunk)
    return bytes(payload)


def _generation_json(generation) -> dict[str, Any] | None:
    if generation is None:
        return None
    return {
        "id": generation.id,
        "client_id": generation.client_id,
        "state": generation.state,
        "requested_action": generation.requested_action,
        "created_at": generation.created_at,
        "started_at": generation.started_at,
        "stopped_at": generation.stopped_at,
        "last_upload_at": generation.last_upload_at,
        "last_manifest_at": generation.last_manifest_at,
        "last_sequence": generation.last_sequence,
        "error_code": generation.error_code,
    }


@router.post("/livestream-agent/clients/{client_id}/commands/claim")
def agent_claim(
    client_id: int,
    body: ClaimBody,
    authorization: Optional[str] = Header(default=None),
):
    with Session(engine) as session:
        require_agent_token(session, authorization, client_id=client_id)
        claimed = claim_command(session, client_id=client_id, lease_seconds=body.lease_seconds)
        session.commit()
        return {"claimed": claimed}


@router.post("/livestream-agent/clients/{client_id}/commands/{command_id}/renew")
def agent_renew(
    client_id: int,
    command_id: str,
    body: RenewBody,
    authorization: Optional[str] = Header(default=None),
):
    with Session(engine) as session:
        require_agent_token(session, authorization, client_id=client_id)
        renew_command(
            session,
            client_id=client_id,
            command_id=command_id,
            claim_token=body.claim_token,
            lease_seconds=body.lease_seconds,
        )
        session.commit()
        return {"ok": True}


@router.post("/livestream-agent/clients/{client_id}/commands/{command_id}/complete")
def agent_complete(
    client_id: int,
    command_id: str,
    body: CompleteBody,
    authorization: Optional[str] = Header(default=None),
):
    with Session(engine) as session:
        require_agent_token(session, authorization, client_id=client_id)
        complete_command(
            session,
            client_id=client_id,
            command_id=command_id,
            claim_token=body.claim_token,
            result=body.result,
        )
        session.commit()
        return {"ok": True}


@router.post("/livestream-agent/clients/{client_id}/commands/{command_id}/fail")
def agent_fail(
    client_id: int,
    command_id: str,
    body: FailBody,
    authorization: Optional[str] = Header(default=None),
):
    with Session(engine) as session:
        require_agent_token(session, authorization, client_id=client_id)
        fail_command(
            session,
            client_id=client_id,
            command_id=command_id,
            claim_token=body.claim_token,
            error_code=body.error_code,
            error_message=body.error_message,
            retryable=body.retryable,
        )
        session.commit()
        return {"ok": True}


@router.put("/livestream-agent/clients/{client_id}/status")
def agent_status(
    client_id: int,
    body: AgentStatusBody,
    authorization: Optional[str] = Header(default=None),
):
    if body.schema_version != 1:
        raise HTTPException(status_code=400, detail="Ukendt Livestream status schema_version")
    with Session(engine) as session:
        require_agent_token(session, authorization, client_id=client_id)
        update_agent_status(
            session,
            client_id=client_id,
            observed_state=body.observed_state,
            status_payload=body.status_payload,
            agent_version=body.agent_version,
            boot_id=body.boot_id,
        )
        reconcile_stopping_generation_from_agent_status(
            session,
            client_id=client_id,
            status_payload=body.status_payload,
        )
        recovered = maybe_recover_stale_media(session, client_id)
        session.commit()
        return {"ok": True, "recovery_enqueued": recovered}


@router.post("/livestream-agent/clients/{client_id}/generations/{generation_id}/started")
def agent_generation_started(
    client_id: int,
    generation_id: str,
    authorization: Optional[str] = Header(default=None),
):
    with Session(engine) as session:
        require_agent_token(session, authorization, client_id=client_id)
        generation = generation_started(session, client_id=client_id, generation_id=generation_id)
        session.commit()
        return _generation_json(generation)


@router.post("/livestream-agent/clients/{client_id}/generations/{generation_id}/stopped")
def agent_generation_stopped(
    client_id: int,
    generation_id: str,
    body: StoppedBody,
    authorization: Optional[str] = Header(default=None),
):
    with Session(engine) as session:
        require_agent_token(session, authorization, client_id=client_id)
        generation = generation_stopped(
            session,
            client_id=client_id,
            generation_id=generation_id,
            error_code=body.error_code,
        )
        # A viewer may have returned while a stop command was already leased.
        # In that race, create the next generation only after the old one has
        # actually stopped.  Normal grace-return never reaches this branch.
        if (
            not explicit_stop_latched(session, client_id)
            and active_viewer_count(session, client_id) > 0
            and current_generation(session, client_id) is None
        ):
            request_start(session, client_id, source="viewer_returned_during_stop")
        session.commit()
        return _generation_json(generation)


@router.put("/livestream-agent/clients/{client_id}/generations/{generation_id}/files/{filename}")
async def agent_upload_file(
    client_id: int,
    generation_id: str,
    filename: str,
    request: Request,
    sequence: int = Query(default=0, ge=0),
    sha256: str = Query(min_length=64, max_length=64),
    authorization: Optional[str] = Header(default=None),
):
    # Authenticate before consuming the request body so unauthenticated callers
    # cannot make the service buffer an arbitrary upload. The body is then
    # streamed with the same hard limit enforced by the storage layer.
    with Session(engine) as auth_session:
        require_agent_token(auth_session, authorization, client_id=client_id)

    payload = await _read_bounded_body(request, maximum=MAX_HLS_FILE_BYTES)
    with Session(engine) as session:
        write_hls_file(
            session,
            client_id=client_id,
            generation_id=generation_id,
            filename=filename,
            payload=payload,
            sha256=sha256,
            sequence=sequence,
        )
        session.commit()
        return {"ok": True, "generation_id": generation_id, "filename": filename}


@router.post("/livestream-v2/hls/{client_id}/viewer-heartbeat")
def browser_viewer_heartbeat(
    client_id: str,
    body: ViewerHeartbeatBody,
    response: Response,
    user=Depends(get_current_user_or_client),
):
    require_hls_access(user, client_id)
    _require_active_platform_client(int(client_id))
    _no_cache(response)
    cid = int(client_id)
    with Session(engine) as session:
        viewer, generation, command = viewer_heartbeat(
            session,
            client_id=cid,
            principal=user,
            viewer_id=body.viewer_id,
            source=body.source,
        )
        session.commit()
        return {
            "ok": True,
            "viewer_id": viewer.viewer_id,
            "active_viewers": active_viewer_count(session, cid),
            "heartbeat_seconds": VIEWER_HEARTBEAT_SECONDS,
            "lease_seconds": VIEWER_LEASE_SECONDS,
            "stop_grace_seconds": VIEWER_STOP_GRACE_SECONDS,
            "generation": _generation_json(generation),
            "start_enqueued": command is not None,
        }


@router.post("/livestream-v2/hls/{client_id}/viewer-leave")
def browser_viewer_leave(
    client_id: str,
    body: ViewerLeaveBody,
    response: Response,
    user=Depends(get_current_user_or_client),
):
    require_hls_access(user, client_id)
    _no_cache(response)
    cid = int(client_id)
    with Session(engine) as session:
        viewer = viewer_leave(
            session,
            client_id=cid,
            principal=user,
            viewer_id=body.viewer_id,
            source=body.source,
        )
        count = active_viewer_count(session, cid)
        session.commit()
        return {
            "ok": True,
            "viewer_id": body.viewer_id,
            "removed": viewer is not None,
            "active_viewers": count,
            "stop_grace_seconds": VIEWER_STOP_GRACE_SECONDS,
        }


@router.get("/livestream-v2/hls/{client_id}/viewer-status")
def browser_viewer_status(
    client_id: str,
    response: Response,
    user=Depends(get_current_user_or_client),
):
    require_hls_access(user, client_id)
    _require_active_platform_client(int(client_id))
    _no_cache(response)
    with Session(engine) as session:
        return {
            "client_id": int(client_id),
            "active_viewers": active_viewer_count(session, int(client_id)),
            "heartbeat_seconds": VIEWER_HEARTBEAT_SECONDS,
            "lease_seconds": VIEWER_LEASE_SECONDS,
            "stop_grace_seconds": VIEWER_STOP_GRACE_SECONDS,
        }


@router.post("/livestream-v2/clients/{client_id}/command")
def browser_command(
    client_id: str,
    body: BrowserCommandBody,
    response: Response,
    user=Depends(get_current_user_or_client),
):
    _require_browser_control_access(user, client_id)
    _require_active_platform_client(int(client_id))
    _no_cache(response)
    cid = int(client_id)
    action = str(body.action or "").strip().lower()
    with Session(engine) as session:
        if action == "livestream_start":
            generation, command = request_start(session, cid, source=body.source or "browser_manual_start")
        elif action == "livestream_stop":
            generation, command = request_stop(
                session,
                cid,
                source=body.source or "browser_manual_stop",
                explicit=True,
            )
        elif action == "livestream_restart":
            generation, command = request_restart(session, cid, source=body.source or "browser_manual_restart")
        else:
            raise HTTPException(status_code=400, detail="Ugyldig Livestream-kommando")
        session.commit()
        return {
            "ok": True,
            "action": action,
            "generation_id": generation.id if generation else None,
            "already_requested": command is None,
        }
