from __future__ import annotations

from datetime import timezone
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Client, ClientDomainCredential, ClientDomainStatus, LivestreamGeneration, LivestreamViewer, User, utcnow
from .security import (
    create_client_token,
    create_user_session,
    credential_digest,
    new_credential_secret,
    require_client_credential,
    require_user,
    verify_password,
)
from .services import (
    active_viewer_count,
    claim_command,
    complete_command,
    current_generation,
    delete_generation_files,
    ensure_current_generation,
    fail_command,
    generation_root,
    maybe_recover_stale_media,
    renew_command,
    request_restart,
    request_start,
    request_stop,
    safe_hls_filename,
    viewer_enter,
    viewer_heartbeat,
    viewer_leave,
    write_hls_file,
)

router = APIRouter()


class LoginBody(BaseModel):
    email: str
    password: str


class ClientCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    id: int | None = Field(default=None, ge=1)


class ClientTokenBody(BaseModel):
    client_id: int
    credential_id: str
    domain: str
    client_secret: str


class ClaimBody(BaseModel):
    lease_seconds: int = Field(default=60, ge=10, le=300)


class RenewBody(BaseModel):
    claim_token: str = Field(min_length=20)
    lease_seconds: int = Field(default=60, ge=10, le=300)


class CompleteBody(BaseModel):
    claim_token: str = Field(min_length=20)
    result: dict[str, Any] = Field(default_factory=dict)


class FailBody(BaseModel):
    claim_token: str = Field(min_length=20)
    error_code: str = Field(min_length=1, max_length=128)
    error_message: str = Field(default="", max_length=2000)
    retryable: bool = False


class AgentStatusBody(BaseModel):
    schema_version: int
    observed_state: str = Field(min_length=1, max_length=64)
    status_payload: dict[str, Any] = Field(default_factory=dict)
    agent_version: str = Field(min_length=1, max_length=64)
    boot_id: str | None = Field(default=None, max_length=128)


class StoppedBody(BaseModel):
    error_code: str | None = Field(default=None, max_length=128)


def _user(request: Request, db: Session) -> User:
    return require_user(request, db)


def _admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


def _owned_client(db: Session, user: User, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if client is None or client.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _agent(db: Session, authorization: str | None, client_id: int) -> ClientDomainCredential:
    credential, _ = require_client_credential(db, authorization, domain="livestream")
    if credential.client_id != client_id:
        raise HTTPException(status_code=403, detail="Token belongs to another client")
    return credential


def _generation_json(generation: LivestreamGeneration | None) -> dict[str, Any] | None:
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


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/auth/login")
def login(body: LoginBody, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_user_session(user)
    response.set_cookie(
        "cf_session",
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path="/",
    )
    return {"id": user.id, "email": user.email, "role": user.role}


@router.post("/api/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie("cf_session", path="/")
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _user(request, db)
    return {"id": user.id, "email": user.email, "role": user.role, "organization_id": user.organization_id}


@router.post("/api/client-auth/token")
def client_token(body: ClientTokenBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.domain != "livestream":
        raise HTTPException(status_code=403, detail="Only livestream domain is enabled in this repository")
    try:
        uuid.UUID(body.credential_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid credential") from exc
    credential = db.get(ClientDomainCredential, body.credential_id)
    if (
        credential is None
        or credential.client_id != body.client_id
        or credential.domain != body.domain
        or credential.revoked_at is not None
        or not __import__("secrets").compare_digest(credential.secret_digest, credential_digest(body.client_secret))
    ):
        raise HTTPException(status_code=401, detail="Invalid credential")
    token, expires_at = create_client_token(credential)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.client_token_ttl_seconds,
        "client_id": credential.client_id,
        "credential_id": credential.id,
        "domain": credential.domain,
        "audience": f"clientflow-domain:{credential.domain}",
        "scope": f"clientflow:{credential.domain}",
        "issuer": settings.token_issuer,
        "token_version": credential.token_version,
        "expires_at": expires_at,
    }


@router.get("/api/clients")
def clients(request: Request, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    user = _user(request, db)
    rows = db.scalars(
        select(Client).where(Client.organization_id == user.organization_id).order_by(Client.name.asc())
    ).all()
    result: list[dict[str, Any]] = []
    for client in rows:
        generation = current_generation(db, client.id)
        status_row = db.scalar(
            select(ClientDomainStatus).where(
                ClientDomainStatus.client_id == client.id,
                ClientDomainStatus.domain == "livestream",
            )
        )
        result.append(
            {
                "id": client.id,
                "name": client.name,
                "is_active": client.is_active,
                "livestream_state": generation.state if generation else "stopped",
                "agent_seen_at": status_row.updated_at if status_row else None,
            }
        )
    return result


@router.post("/api/clients", status_code=201)
def create_client(body: ClientCreateBody, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _admin(request, db)
    client = Client(id=body.id, organization_id=user.organization_id, name=body.name.strip()) if body.id else Client(organization_id=user.organization_id, name=body.name.strip())
    db.add(client)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Client name already exists")
    db.refresh(client)
    return {"id": client.id, "name": client.name}


@router.post("/api/clients/{client_id}/livestream/credential")
def rotate_livestream_credential(client_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _admin(request, db)
    _owned_client(db, user, client_id)
    now = utcnow()
    old_credentials = db.scalars(
        select(ClientDomainCredential).where(
            ClientDomainCredential.client_id == client_id,
            ClientDomainCredential.domain == "livestream",
            ClientDomainCredential.revoked_at.is_(None),
        )
    ).all()
    for row in old_credentials:
        row.revoked_at = now
    secret = new_credential_secret()
    credential = ClientDomainCredential(
        id=str(uuid.uuid4()),
        client_id=client_id,
        domain="livestream",
        secret_digest=credential_digest(secret),
        token_version=1,
    )
    db.add(credential)
    db.commit()
    return {
        "schema_version": 1,
        "backend_url": settings.public_base_url,
        "client_id": client_id,
        "domain": "livestream",
        "credential_id": credential.id,
        "client_secret": secret,
        "token_issuer": settings.token_issuer,
    }


@router.get("/api/clients/{client_id}/livestream")
def livestream_status(client_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _user(request, db)
    _owned_client(db, user, client_id)
    generation = current_generation(db, client_id)
    status_row = db.scalar(
        select(ClientDomainStatus).where(
            ClientDomainStatus.client_id == client_id,
            ClientDomainStatus.domain == "livestream",
        )
    )
    playlist_ready = False
    media_age_seconds: float | None = None
    if generation:
        playlist_ready = (generation_root(client_id, generation.id) / "index.m3u8").is_file()
        reference = generation.last_upload_at or generation.started_at or generation.created_at
        reference = reference if reference.tzinfo is not None else reference.replace(tzinfo=timezone.utc)
        media_age_seconds = max(0.0, (utcnow() - reference).total_seconds())
    return {
        "generation": _generation_json(generation),
        "playlist_ready": playlist_ready,
        "media_age_seconds": media_age_seconds,
        "viewers": {
            "active": active_viewer_count(db, client_id),
            "heartbeat_seconds": settings.viewer_heartbeat_seconds,
            "lease_seconds": settings.viewer_lease_seconds,
            "stop_grace_seconds": settings.viewer_stop_grace_seconds,
        },
        "agent": None
        if status_row is None
        else {
            "observed_state": status_row.observed_state,
            "status_payload": status_row.status_payload,
            "agent_version": status_row.agent_version,
            "boot_id": status_row.boot_id,
            "updated_at": status_row.updated_at,
        },
    }


@router.post("/api/clients/{client_id}/livestream/viewers", status_code=201)
def livestream_viewer_enter(client_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _user(request, db)
    _owned_client(db, user, client_id)
    viewer, generation, command = viewer_enter(db, client_id=client_id, user_id=user.id)
    db.commit()
    return {
        "viewer_id": viewer.id,
        "heartbeat_seconds": settings.viewer_heartbeat_seconds,
        "lease_seconds": settings.viewer_lease_seconds,
        "stop_grace_seconds": settings.viewer_stop_grace_seconds,
        "generation": _generation_json(generation),
        "command_id": command.id if command else None,
    }


@router.post("/api/clients/{client_id}/livestream/viewers/{viewer_id}/heartbeat")
def livestream_viewer_heartbeat(
    client_id: int,
    viewer_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = _user(request, db)
    _owned_client(db, user, client_id)
    viewer, generation, command = viewer_heartbeat(
        db,
        client_id=client_id,
        user_id=user.id,
        viewer_id=viewer_id,
    )
    db.commit()
    return {
        "ok": True,
        "viewer_id": viewer.id,
        "generation": _generation_json(generation),
        "command_id": command.id if command else None,
    }


@router.post("/api/clients/{client_id}/livestream/viewers/{viewer_id}/leave")
def livestream_viewer_leave(
    client_id: int,
    viewer_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    user = _user(request, db)
    _owned_client(db, user, client_id)
    viewer_leave(db, client_id=client_id, user_id=user.id, viewer_id=viewer_id)
    db.commit()
    return {"ok": True}


@router.post("/api/clients/{client_id}/livestream/start")
def livestream_start(client_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _admin(request, db)
    _owned_client(db, user, client_id)
    generation, command = request_start(db, client_id)
    db.commit()
    return {"generation": _generation_json(generation), "command_id": command.id if command else None}


@router.post("/api/clients/{client_id}/livestream/restart")
def livestream_restart(client_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _admin(request, db)
    _owned_client(db, user, client_id)
    generation, command = request_restart(db, client_id)
    db.commit()
    return {"generation": _generation_json(generation), "command_id": command.id}


@router.post("/api/clients/{client_id}/livestream/stop")
def livestream_stop(client_id: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _admin(request, db)
    _owned_client(db, user, client_id)
    generation, command = request_stop(db, client_id)
    db.commit()
    return {"generation": _generation_json(generation), "command_id": command.id if command else None}


@router.post("/api/livestream-agent/clients/{client_id}/commands/claim")
def agent_claim(
    client_id: int,
    body: ClaimBody,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _agent(db, authorization, client_id)
    claimed = claim_command(db, client_id=client_id, lease_seconds=body.lease_seconds)
    db.commit()
    return {"claimed": claimed}


@router.post("/api/livestream-agent/clients/{client_id}/commands/{command_id}/renew")
def agent_renew(
    client_id: int,
    command_id: str,
    body: RenewBody,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    _agent(db, authorization, client_id)
    renew_command(db, client_id=client_id, command_id=command_id, claim_token=body.claim_token, lease_seconds=body.lease_seconds)
    db.commit()
    return {"ok": True}


@router.post("/api/livestream-agent/clients/{client_id}/commands/{command_id}/complete")
def agent_complete(
    client_id: int,
    command_id: str,
    body: CompleteBody,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    _agent(db, authorization, client_id)
    complete_command(db, client_id=client_id, command_id=command_id, claim_token=body.claim_token, result=body.result)
    db.commit()
    return {"ok": True}


@router.post("/api/livestream-agent/clients/{client_id}/commands/{command_id}/fail")
def agent_fail(
    client_id: int,
    command_id: str,
    body: FailBody,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    _agent(db, authorization, client_id)
    fail_command(
        db,
        client_id=client_id,
        command_id=command_id,
        claim_token=body.claim_token,
        error_code=body.error_code,
        error_message=body.error_message,
        retryable=body.retryable,
    )
    db.commit()
    return {"ok": True}


@router.put("/api/livestream-agent/clients/{client_id}/status")
def agent_status(
    client_id: int,
    body: AgentStatusBody,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _agent(db, authorization, client_id)
    if body.schema_version != 1:
        raise HTTPException(status_code=400, detail="Unsupported status schema_version")
    row = db.scalar(
        select(ClientDomainStatus).where(
            ClientDomainStatus.client_id == client_id,
            ClientDomainStatus.domain == "livestream",
        )
    )
    if row is None:
        row = ClientDomainStatus(
            client_id=client_id,
            domain="livestream",
            observed_state=body.observed_state,
            status_payload=body.status_payload,
            agent_version=body.agent_version,
            boot_id=body.boot_id,
        )
        db.add(row)
    else:
        row.observed_state = body.observed_state
        row.status_payload = body.status_payload
        row.agent_version = body.agent_version
        row.boot_id = body.boot_id
        row.updated_at = utcnow()
    recovered = maybe_recover_stale_media(db, client_id)
    db.commit()
    return {"ok": True, "recovery_enqueued": recovered}


@router.post("/api/livestream-agent/clients/{client_id}/generations/{generation_id}/started")
def agent_generation_started(
    client_id: int,
    generation_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _agent(db, authorization, client_id)
    generation = ensure_current_generation(db, client_id=client_id, generation_id=generation_id, allowed_states={"starting", "running"})
    generation.state = "running"
    generation.started_at = generation.started_at or utcnow()
    generation.error_code = None
    db.commit()
    return _generation_json(generation) or {}


@router.post("/api/livestream-agent/clients/{client_id}/generations/{generation_id}/stopped")
def agent_generation_stopped(
    client_id: int,
    generation_id: str,
    body: StoppedBody,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _agent(db, authorization, client_id)
    generation = db.get(LivestreamGeneration, generation_id)
    if generation is None or generation.client_id != client_id:
        raise HTTPException(status_code=404, detail="Generation not found")
    if body.error_code:
        generation.state = "failed"
        generation.error_code = body.error_code
    elif generation.state not in {"failed", "superseded"}:
        generation.state = "stopped"
    generation.stopped_at = utcnow()
    if active_viewer_count(db, client_id) > 0 and current_generation(db, client_id) is None:
        request_start(db, client_id)
    db.commit()
    delete_generation_files(client_id, generation_id)
    return _generation_json(generation) or {}


@router.put("/api/livestream-agent/clients/{client_id}/generations/{generation_id}/files/{filename}")
async def agent_upload_file(
    client_id: int,
    generation_id: str,
    filename: str,
    request: Request,
    sequence: int,
    sha256: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _agent(db, authorization, client_id)
    generation = ensure_current_generation(db, client_id=client_id, generation_id=generation_id, allowed_states={"starting", "running"})
    if sequence < 0 or sequence > 2_147_483_647:
        raise HTTPException(status_code=400, detail="Invalid sequence")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > 64 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="HLS file too large")
    payload = await request.body()
    safe_name = safe_hls_filename(filename)
    write_hls_file(client_id=client_id, generation_id=generation_id, filename=safe_name, payload=payload, sha256=sha256)
    now = utcnow()
    generation.last_upload_at = now
    generation.last_sequence = max(generation.last_sequence or 0, sequence)
    if safe_name == "index.m3u8":
        generation.last_manifest_at = now
    db.commit()
    return {"ok": True, "generation_id": generation_id, "filename": safe_name, "sequence": sequence}


@router.get("/api/clients/{client_id}/livestream/hls/{filename}")
def serve_hls(filename: str, client_id: int, request: Request, db: Session = Depends(get_db)) -> FileResponse:
    user = _user(request, db)
    _owned_client(db, user, client_id)
    generation = current_generation(db, client_id)
    if generation is None or generation.state not in {"starting", "running", "stopping"}:
        raise HTTPException(status_code=404, detail="Livestream is stopped")
    safe_name = safe_hls_filename(filename)
    path = generation_root(client_id, generation.id) / safe_name
    if not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=404, detail="HLS file not ready")
    media_type = {
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
        ".m4s": "video/iso.segment",
        ".mp4": "video/mp4",
    }[path.suffix.lower()]
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})
