"""Shared ClientFlow control-plane primitives for status/display/system.

Livestream, Terminal and Remote Desktop own isolated authentication/control
planes and must never pass through this module.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
import uuid
from typing import Any

import jwt
from fastapi import HTTPException, status
from sqlmodel import Session, select

from .auth import SECRET_KEY, verify_password
from .client_domain_models import ClientCommand, ClientDomainCredential, ClientDomainStatus
from .models import Client

SHARED_DOMAINS = frozenset({"status", "display", "system"})
COMMAND_DOMAINS = frozenset({"display", "system"})
DOMAIN_TOKEN_TTL_SECONDS = min(
    max(60, int(os.getenv("CLIENTFLOW_DOMAIN_TOKEN_TTL_SECONDS", "600"))),
    3600,
)
DOMAIN_TOKEN_ISSUER = (
    os.getenv("CLIENTFLOW_DOMAIN_TOKEN_ISSUER") or "planiq-display-api"
).strip()
DOMAIN_TOKEN_ALGORITHM = "HS256"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _validate_domain(domain: str, *, commands: bool = False) -> str:
    allowed = COMMAND_DOMAINS if commands else SHARED_DOMAINS
    if domain not in allowed:
        raise HTTPException(status_code=404, detail="Domæne-endpoint ikke fundet")
    return domain


def _validate_credential_id(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Ugyldigt credential") from exc


def authenticate_shared_credential(
    session: Session,
    *,
    client_id: int,
    credential_id: str,
    domain: str,
    client_secret: str,
) -> ClientDomainCredential:
    _validate_domain(domain)
    credential_id = _validate_credential_id(credential_id)
    credential = session.get(ClientDomainCredential, credential_id)
    client = session.get(Client, client_id)
    if (
        credential is None
        or client is None
        or str(getattr(client, "status", "") or "").lower() != "approved"
        or credential.client_id != client_id
        or credential.domain != domain
        or credential.revoked_at is not None
    ):
        raise HTTPException(status_code=401, detail="Ugyldigt credential")
    try:
        verified = verify_password(client_secret, credential.secret_hash)
    except Exception:
        verified = False
    if not verified:
        raise HTTPException(status_code=401, detail="Ugyldigt credential")
    credential.last_used_at = utcnow()
    session.add(credential)
    return credential


def create_shared_domain_token(credential: ClientDomainCredential) -> tuple[str, datetime]:
    _validate_domain(credential.domain)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=DOMAIN_TOKEN_TTL_SECONDS)
    audience = f"clientflow-domain:{credential.domain}"
    scope = f"clientflow:{credential.domain}"
    claims = {
        "iss": DOMAIN_TOKEN_ISSUER,
        "sub": f"client:{credential.client_id}:{credential.id}",
        "principal": "client_domain",
        "client_id": credential.client_id,
        "credential_id": credential.id,
        "domain": credential.domain,
        "scope": scope,
        "aud": audience,
        "token_version": credential.token_version,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, SECRET_KEY, algorithm=DOMAIN_TOKEN_ALGORITHM)
    return token, expires_at


def issue_shared_domain_token_response(
    session: Session,
    *,
    client_id: int,
    credential_id: str,
    domain: str,
    client_secret: str,
) -> dict[str, Any]:
    credential = authenticate_shared_credential(
        session,
        client_id=client_id,
        credential_id=credential_id,
        domain=domain,
        client_secret=client_secret,
    )
    token, expires_at = create_shared_domain_token(credential)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": DOMAIN_TOKEN_TTL_SECONDS,
        "client_id": credential.client_id,
        "credential_id": credential.id,
        "domain": credential.domain,
        "audience": f"clientflow-domain:{credential.domain}",
        "scope": f"clientflow:{credential.domain}",
        "issuer": DOMAIN_TOKEN_ISSUER,
        "token_version": credential.token_version,
        "expires_at": expires_at,
    }


def require_shared_agent_token(
    session: Session,
    authorization: str | None,
    *,
    client_id: int,
    domain: str,
) -> ClientDomainCredential:
    _validate_domain(domain)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token mangler")
    token = authorization[7:].strip()
    try:
        claims = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[DOMAIN_TOKEN_ALGORITHM],
            audience=f"clientflow-domain:{domain}",
            issuer=DOMAIN_TOKEN_ISSUER,
            options={
                "require": [
                    "exp", "iat", "nbf", "jti", "sub", "client_id",
                    "credential_id", "domain", "scope", "token_version",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Ugyldigt domæne-agent token") from exc

    credential_id = str(claims.get("credential_id") or "")
    if (
        claims.get("principal") != "client_domain"
        or claims.get("domain") != domain
        or claims.get("scope") != f"clientflow:{domain}"
        or int(claims.get("client_id") or 0) != int(client_id)
        or claims.get("sub") != f"client:{client_id}:{credential_id}"
    ):
        raise HTTPException(status_code=403, detail="Token tilhører et andet domæne eller klient")

    credential = session.get(ClientDomainCredential, credential_id)
    client = session.get(Client, client_id)
    if (
        credential is None
        or client is None
        or str(getattr(client, "status", "") or "").lower() != "approved"
        or getattr(client, "deleted_at", None) is not None
        or credential.client_id != client_id
        or credential.domain != domain
        or credential.revoked_at is not None
        or credential.token_version != int(claims["token_version"])
    ):
        raise HTTPException(status_code=401, detail="Credential er tilbagekaldt, forældet eller klienten er deaktiveret")
    return credential


def upsert_shared_status(
    session: Session,
    *,
    credential: ClientDomainCredential,
    schema_version: int,
    observed_state: str,
    status_payload: dict[str, Any],
    agent_version: str | None,
    boot_id: str | None,
) -> ClientDomainStatus:
    if schema_version != 1:
        raise HTTPException(status_code=422, detail="Status schema_version understøttes ikke")
    row = session.exec(
        select(ClientDomainStatus).where(
            ClientDomainStatus.client_id == credential.client_id,
            ClientDomainStatus.domain == credential.domain,
        )
    ).first()
    if row is None:
        row = ClientDomainStatus(
            id=str(uuid.uuid4()),
            client_id=credential.client_id,
            domain=credential.domain,
            credential_id=credential.id,
            reported_at=utcnow(),
        )
    row.schema_version = schema_version
    row.observed_state = observed_state[:80]
    row.status_payload = status_payload
    row.agent_version = agent_version[:80] if agent_version else None
    row.boot_id = boot_id[:128] if boot_id else None
    row.credential_id = credential.id
    row.reported_at = utcnow()
    session.add(row)
    return row


def _claim_digest(claim_token: str) -> str:
    return hashlib.sha256(claim_token.encode("utf-8")).hexdigest()


def _clear_claim(row: ClientCommand) -> None:
    row.claim_token_hash = None
    row.claimed_by_credential_id = None
    row.claimed_at = None
    row.lease_expires_at = None


def _reconcile_command_state(
    session: Session,
    *,
    client_id: int,
    domain: str,
    now: datetime,
) -> None:
    # Scope reconciliation to exactly one shared command domain/client.
    rows = session.exec(
        select(ClientCommand)
        .where(
            ClientCommand.client_id == client_id,
            ClientCommand.domain == domain,
            ClientCommand.status.in_(["queued", "claimed"]),
        )
        .with_for_update()
    ).all()
    for row in rows:
        if row.expires_at <= now:
            row.status = "expired"
            row.completed_at = now
            row.error_code = "command_expired"
            row.error_message = "Kommandoens udløbstidspunkt er passeret"
            _clear_claim(row)
            session.add(row)
            continue
        if row.status == "claimed" and row.lease_expires_at is not None and row.lease_expires_at <= now:
            if row.attempt_count >= row.max_attempts:
                row.status = "failed"
                row.completed_at = now
                row.error_code = "lease_attempts_exhausted"
                row.error_message = "Kommandoens lease udløb og max_attempts er nået"
            else:
                row.status = "queued"
                row.available_at = now
            _clear_claim(row)
            session.add(row)


def claim_shared_command(
    session: Session,
    *,
    credential: ClientDomainCredential,
    lease_seconds: int,
) -> dict[str, Any]:
    domain = _validate_domain(credential.domain, commands=True)
    lease_seconds = min(max(int(lease_seconds), 10), 300)
    now = utcnow()
    _reconcile_command_state(session, client_id=credential.client_id, domain=domain, now=now)

    row = session.exec(
        select(ClientCommand)
        .where(
            ClientCommand.client_id == credential.client_id,
            ClientCommand.domain == domain,
            ClientCommand.status == "queued",
            ClientCommand.available_at <= now,
            ClientCommand.expires_at > now,
            ClientCommand.attempt_count < ClientCommand.max_attempts,
        )
        .order_by(ClientCommand.available_at, ClientCommand.requested_at, ClientCommand.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if row is None:
        return {"claimed": None}

    claim_token = secrets.token_urlsafe(32)
    row.status = "claimed"
    row.claim_token_hash = _claim_digest(claim_token)
    row.claimed_by_credential_id = credential.id
    row.claimed_at = now
    row.lease_expires_at = now + timedelta(seconds=lease_seconds)
    row.attempt_count += 1
    session.add(row)
    return {
        "claimed": {
            "command": {
                "id": row.id,
                "client_id": row.client_id,
                "domain": row.domain,
                "command_type": row.command_type,
                "schema_version": row.schema_version,
                "payload": row.payload,
                "requested_at": row.requested_at,
                "available_at": row.available_at,
                "expires_at": row.expires_at,
                "attempt_count": row.attempt_count,
                "max_attempts": row.max_attempts,
            },
            "claim_token": claim_token,
            "lease_expires_at": row.lease_expires_at,
        }
    }


def _require_claimed_command(
    session: Session,
    *,
    credential: ClientDomainCredential,
    command_id: str,
    claim_token: str,
) -> ClientCommand:
    domain = _validate_domain(credential.domain, commands=True)
    row = session.exec(
        select(ClientCommand)
        .where(
            ClientCommand.id == command_id,
            ClientCommand.client_id == credential.client_id,
            ClientCommand.domain == domain,
        )
        .with_for_update()
    ).first()
    now = utcnow()
    if (
        row is None
        or row.status != "claimed"
        or row.claimed_by_credential_id != credential.id
        or not row.claim_token_hash
        or not secrets.compare_digest(row.claim_token_hash, _claim_digest(claim_token))
    ):
        raise HTTPException(status_code=409, detail="Command claim er ikke længere gyldigt")
    if row.expires_at <= now or row.lease_expires_at is None or row.lease_expires_at <= now:
        raise HTTPException(status_code=409, detail="Command lease er udløbet")
    return row


def renew_shared_command(
    session: Session,
    *,
    credential: ClientDomainCredential,
    command_id: str,
    claim_token: str,
    lease_seconds: int,
) -> dict[str, Any]:
    row = _require_claimed_command(
        session,
        credential=credential,
        command_id=command_id,
        claim_token=claim_token,
    )
    lease_seconds = min(max(int(lease_seconds), 10), 300)
    row.lease_expires_at = min(
        utcnow() + timedelta(seconds=lease_seconds),
        row.expires_at,
    )
    session.add(row)
    return {"renewed": True, "lease_expires_at": row.lease_expires_at}


def complete_shared_command(
    session: Session,
    *,
    credential: ClientDomainCredential,
    command_id: str,
    claim_token: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    row = _require_claimed_command(
        session,
        credential=credential,
        command_id=command_id,
        claim_token=claim_token,
    )
    row.status = "succeeded"
    row.result = result
    row.error_code = None
    row.error_message = None
    row.completed_at = utcnow()
    _clear_claim(row)
    session.add(row)
    return {"completed": True, "status": row.status}


def fail_shared_command(
    session: Session,
    *,
    credential: ClientDomainCredential,
    command_id: str,
    claim_token: str,
    error_code: str,
    error_message: str,
    retryable: bool,
) -> dict[str, Any]:
    row = _require_claimed_command(
        session,
        credential=credential,
        command_id=command_id,
        claim_token=claim_token,
    )
    now = utcnow()
    row.error_code = error_code[:120] or "command_failed"
    row.error_message = error_message[:2000]
    if retryable and row.attempt_count < row.max_attempts and row.expires_at > now:
        row.status = "queued"
        # Small bounded delay prevents a failing local broker from hot-looping.
        row.available_at = min(now + timedelta(seconds=min(30, 2 ** row.attempt_count)), row.expires_at)
        row.completed_at = None
    else:
        row.status = "failed"
        row.completed_at = now
    _clear_claim(row)
    session.add(row)
    return {"failed": True, "status": row.status}
