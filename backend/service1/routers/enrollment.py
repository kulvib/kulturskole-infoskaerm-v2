from __future__ import annotations

import base64
import binascii
from datetime import timedelta
import hashlib
import hmac
import os
import secrets
import string
from typing import List, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from ..audit import add_audit_log
from ..auth import get_current_superadmin_user, get_password_hash, verify_password
from ..client_domain_models import ClientDomainCredential
from ..db import get_session
from ..enrollment_models import ClientEnrollmentReceipt, ClientSystemEncryptionKey
from ..livestream_v2 import TOKEN_ISSUER as LIVESTREAM_TOKEN_ISSUER, credential_digest
from ..livestream_v2_models import LivestreamV2Credential
from ..models import Client, EnrollmentToken, Organization, User, utcnow
from ..rate_limit import enforce_request_rate_limit
from ..remote_desktop_v2 import DOMAIN_TOKEN_ISSUER as REMOTE_DESKTOP_TOKEN_ISSUER
from ..remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from ..shared_domain import DOMAIN_TOKEN_ISSUER as SHARED_TOKEN_ISSUER
from ..terminal_v2 import (
    DOMAIN_TOKEN_ISSUER as TERMINAL_TOKEN_ISSUER,
    ROOT_GRANT_ALGORITHM,
    ROOT_GRANT_AUDIENCE,
    ROOT_GRANT_ISSUER,
)
from ..terminal_v2_models import TerminalClient, TerminalCredential

router = APIRouter()

TOKEN_ALPHABET = string.ascii_uppercase + string.digits
ENROLLMENT_RESUME_HOURS = 24
DOMAIN_NAMES = ("status", "display", "livestream", "remote_desktop", "terminal", "system")
SHARED_CREDENTIAL_DOMAINS = ("status", "display", "system")
_RSA_ENCRYPTION_OID_DER = bytes.fromhex("06092a864886f70d010101")


def _generate_enrollment_code() -> str:
    parts = []
    for _ in range(3):
        parts.append("".join(secrets.choice(TOKEN_ALPHABET) for _ in range(4)))
    return "CF-" + "-".join(parts)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_seed(value: str) -> bytes:
    raw = str(value or "").strip()
    try:
        seed = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="credential_seed_b64 er ugyldig") from exc
    if len(seed) != 32:
        raise HTTPException(status_code=422, detail="credential_seed_b64 skal være 32 bytes")
    return seed


def _normalize_install_id(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="install_id er ugyldigt") from exc


def _derive_resume_proof(seed: bytes, install_id: str) -> str:
    context = f"clientflow-enrollment-resume-v1:{install_id}".encode()
    return _encode(hmac.new(seed, context, hashlib.sha256).digest())


def _resume_proof_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _derive_domain_secret(seed: bytes, *, client_id: int, credential_id: str, domain: str) -> str:
    context = f"clientflow-domain-secret-v1:{client_id}:{credential_id}:{domain}".encode()
    return f"cf_{domain}_{_encode(hmac.new(seed, context, hashlib.sha256).digest())}"


def _canonical_public_key(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    begin = "-----BEGIN PUBLIC KEY-----"
    end = "-----END PUBLIC KEY-----"
    if not raw.startswith(begin) or not raw.endswith(end) or len(raw) > 16_384:
        raise HTTPException(status_code=422, detail="system_encryption_public_key_pem er ugyldig")
    body = "".join(raw[len(begin):-len(end)].split())
    try:
        der = base64.b64decode(body, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="system_encryption_public_key_pem er ugyldig") from exc
    if not 256 <= len(der) <= 4096 or _RSA_ENCRYPTION_OID_DER not in der[:128]:
        raise HTTPException(status_code=422, detail="System encryption key skal være en RSA public key")
    key_id = hashlib.sha256(der).hexdigest()[:32]
    canonical = begin + "\n"
    canonical += "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    canonical += "\n" + end + "\n"
    return canonical, key_id


def _canonical_token_issuer() -> str:
    issuers = {
        str(SHARED_TOKEN_ISSUER).strip(),
        str(LIVESTREAM_TOKEN_ISSUER).strip(),
        str(TERMINAL_TOKEN_ISSUER).strip(),
        str(REMOTE_DESKTOP_TOKEN_ISSUER).strip(),
    }
    if "" in issuers or len(issuers) != 1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ClientFlow domain token issuers er ikke konfigureret ens",
        )
    return next(iter(issuers))


def _root_terminal_broker(terminal_credential_id: str) -> dict[str, str]:
    key_b64 = str(os.getenv("CLIENTFLOW_ROOT_TERMINAL_KEY_B64") or "").strip()
    key_id = str(os.getenv("CLIENTFLOW_ROOT_TERMINAL_KEY_ID") or "").strip()
    if not key_b64 or not key_id or len(key_id) > 128:
        raise HTTPException(status_code=503, detail="Admin-terminalens root-grant nøgle er ikke konfigureret")
    try:
        key = base64.urlsafe_b64decode(key_b64 + "=" * (-len(key_b64) % 4))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Admin-terminalens root-grant nøgle er ugyldig") from exc
    if len(key) != 32 or ROOT_GRANT_ALGORITHM != "HS256":
        raise HTTPException(status_code=503, detail="Admin-terminalens root-grant kontrakt er ugyldig")
    return {
        "terminal_credential_id": terminal_credential_id,
        "key_id": key_id,
        "algorithm": ROOT_GRANT_ALGORITHM,
        "audience": ROOT_GRANT_AUDIENCE,
        "issuer": ROOT_GRANT_ISSUER,
        "verification_key_b64": key_b64.rstrip("="),
    }


class EnrollmentTokenCreate(BaseModel):
    expires_in_hours: int = PydanticField(default=72, ge=1, le=24 * 30)
    organization_id: Optional[int] = None
    note: Optional[str] = None


class EnrollmentTokenRead(BaseModel):
    id: int
    code_preview: Optional[str]
    created_at: str
    expires_at: str
    used_at: Optional[str]
    revoked_at: Optional[str]
    used_by_client_id: Optional[int]
    used_by_client_name: Optional[str] = None
    used_by_client_locality: Optional[str] = None
    used_by_client_status: Optional[str] = None
    organization_id: Optional[int]
    note: Optional[str]
    is_used: bool
    is_expired: bool
    is_revoked: bool


class EnrollmentTokenCreated(BaseModel):
    id: int
    code: str
    expires_at: str
    note: Optional[str] = None


class EnrollmentCredentialRead(BaseModel):
    domain: str
    credential_id: str


class EnrollmentRootBrokerRead(BaseModel):
    terminal_credential_id: str
    key_id: str
    algorithm: str
    audience: str
    issuer: str
    verification_key_b64: str


class EnrollmentClaimRequest(BaseModel):
    enrollment_code: str = PydanticField(min_length=1, max_length=128)
    install_id: str = PydanticField(min_length=36, max_length=36)
    credential_seed_b64: str = PydanticField(min_length=40, max_length=64)
    resume_proof: str = PydanticField(min_length=32, max_length=128)
    system_encryption_public_key_pem: str = PydanticField(min_length=128, max_length=16_384)
    name: Optional[str] = None
    locality: Optional[str] = None
    hostname: Optional[str] = None
    machine_id: Optional[str] = None
    ubuntu_version: Optional[str] = None
    uptime: Optional[str] = None
    wifi_ip_address: Optional[str] = None
    wifi_mac_address: Optional[str] = None
    lan_ip_address: Optional[str] = None
    lan_mac_address: Optional[str] = None


class EnrollmentClaimResponse(BaseModel):
    client_id: int
    token_issuer: str
    credentials: list[EnrollmentCredentialRead]
    root_terminal_broker: EnrollmentRootBrokerRead
    system_encryption_key_id: str
    status: str
    name: str


class EnrollmentCompleteRequest(BaseModel):
    install_id: str = PydanticField(min_length=36, max_length=36)
    resume_proof: str = PydanticField(min_length=32, max_length=128)


def _token_to_read(token: EnrollmentToken, session: Optional[Session] = None) -> EnrollmentTokenRead:
    now = utcnow()
    is_used = token.used_at is not None
    is_revoked = token.revoked_at is not None
    is_expired = (not is_used) and (not is_revoked) and token.expires_at < now
    used_client = session.get(Client, token.used_by_client_id) if session is not None and token.used_by_client_id else None
    return EnrollmentTokenRead(
        id=token.id,
        code_preview=token.code_preview,
        created_at=token.created_at.isoformat() + "Z",
        expires_at=token.expires_at.isoformat() + "Z",
        used_at=token.used_at.isoformat() + "Z" if token.used_at else None,
        revoked_at=token.revoked_at.isoformat() + "Z" if token.revoked_at else None,
        used_by_client_id=token.used_by_client_id,
        used_by_client_name=used_client.name if used_client else None,
        used_by_client_locality=used_client.locality if used_client else None,
        used_by_client_status=used_client.status if used_client else None,
        organization_id=token.organization_id,
        note=token.note,
        is_used=is_used,
        is_expired=is_expired,
        is_revoked=is_revoked,
    )


def _require_admin_can_use_organization(admin: User, organization_id: Optional[int]):
    if admin.is_superadmin:
        return
    if organization_id is None or organization_id == admin.organization_id:
        return
    raise HTTPException(status_code=403, detail="Du kan kun oprette installationskoder til din egen organisation")


@router.post("/admin/enrollment-tokens", response_model=EnrollmentTokenCreated, status_code=201)
def create_enrollment_token(
    request: Request,
    data: EnrollmentTokenCreate = Body(default_factory=EnrollmentTokenCreate),
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_superadmin_user),
):
    _require_admin_can_use_organization(admin, data.organization_id)
    resolved_organization_id = data.organization_id if data.organization_id is not None else admin.organization_id
    if resolved_organization_id is not None and not session.get(Organization, resolved_organization_id):
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")
    code = _generate_enrollment_code()
    token = EnrollmentToken(
        code_hash=get_password_hash(code),
        code_preview=code[-4:],
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(hours=data.expires_in_hours),
        created_by_user_id=admin.id,
        organization_id=resolved_organization_id,
        note=data.note,
    )
    session.add(token)
    session.flush()
    add_audit_log(
        session,
        action="enrollment_token_created",
        request=request,
        actor=admin,
        entity_type="enrollment_token",
        entity_id=token.id,
        entity_label=token.code_preview,
        target_organization_id=token.organization_id,
        details={"expires_at": token.expires_at.isoformat(), "note": token.note},
    )
    session.commit()
    session.refresh(token)
    return EnrollmentTokenCreated(id=token.id, code=code, expires_at=token.expires_at.isoformat() + "Z", note=token.note)


@router.get("/admin/enrollment-tokens", response_model=List[EnrollmentTokenRead])
def list_enrollment_tokens(
    include_history: bool = False,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_superadmin_user),
):
    stmt = select(EnrollmentToken).order_by(EnrollmentToken.created_at.desc())
    tokens = session.exec(stmt).all()
    if not include_history:
        now = utcnow()
        tokens = [t for t in tokens if t.used_at is not None or (t.revoked_at is None and t.expires_at >= now)]
    return [_token_to_read(t, session) for t in tokens]


@router.post("/admin/enrollment-tokens/{token_id}/revoke", response_model=EnrollmentTokenRead)
def revoke_enrollment_token(
    request: Request,
    token_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_superadmin_user),
):
    token = session.get(EnrollmentToken, token_id)
    if not token:
        raise HTTPException(status_code=404, detail="Installationskode ikke fundet")
    _require_admin_can_use_organization(admin, token.organization_id)
    if token.used_at is not None:
        raise HTTPException(status_code=409, detail="Installationskoden er allerede brugt og kan ikke tilbagekaldes")
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        session.add(token)
        add_audit_log(
            session,
            action="enrollment_token_revoked",
            request=request,
            actor=admin,
            entity_type="enrollment_token",
            entity_id=token.id,
            entity_label=token.code_preview,
            target_organization_id=token.organization_id,
            severity="warning",
        )
        session.commit()
        session.refresh(token)
    return _token_to_read(token, session)


def _credential_response(
    session: Session,
    *,
    client: Client,
    seed: bytes,
    system_key: ClientSystemEncryptionKey,
) -> EnrollmentClaimResponse:
    rows: dict[str, str] = {}
    for domain in SHARED_CREDENTIAL_DOMAINS:
        credential = session.exec(
            select(ClientDomainCredential).where(
                ClientDomainCredential.client_id == client.id,
                ClientDomainCredential.domain == domain,
                ClientDomainCredential.revoked_at == None,
            )
        ).one_or_none()
        if credential is None:
            raise HTTPException(status_code=409, detail=f"Enrollment mangler {domain}-credential")
        secret = _derive_domain_secret(seed, client_id=int(client.id), credential_id=credential.id, domain=domain)
        if not verify_password(secret, credential.secret_hash):
            raise HTTPException(status_code=409, detail="Enrollment resume-proof matcher ikke credentials")
        rows[domain] = credential.id

    livestream = session.exec(
        select(LivestreamV2Credential).where(
            LivestreamV2Credential.client_id == client.id,
            LivestreamV2Credential.revoked_at == None,
        )
    ).one_or_none()
    if livestream is None:
        raise HTTPException(status_code=409, detail="Enrollment mangler livestream-credential")
    livestream_secret = _derive_domain_secret(
        seed, client_id=int(client.id), credential_id=livestream.id, domain="livestream"
    )
    if not secrets.compare_digest(livestream.secret_digest, credential_digest(livestream_secret)):
        raise HTTPException(status_code=409, detail="Enrollment resume-proof matcher ikke credentials")
    rows["livestream"] = livestream.id

    terminal = session.exec(
        select(TerminalCredential).where(
            TerminalCredential.client_id == client.id,
            TerminalCredential.revoked_at == None,
        )
    ).one_or_none()
    if terminal is None:
        raise HTTPException(status_code=409, detail="Enrollment mangler terminal-credential")
    terminal_secret = _derive_domain_secret(seed, client_id=int(client.id), credential_id=terminal.id, domain="terminal")
    if not verify_password(terminal_secret, terminal.secret_hash):
        raise HTTPException(status_code=409, detail="Enrollment resume-proof matcher ikke credentials")
    rows["terminal"] = terminal.id

    remote_desktop = session.exec(
        select(RemoteDesktopCredential).where(
            RemoteDesktopCredential.client_id == client.id,
            RemoteDesktopCredential.revoked_at == None,
        )
    ).one_or_none()
    if remote_desktop is None:
        raise HTTPException(status_code=409, detail="Enrollment mangler remote_desktop-credential")
    rd_secret = _derive_domain_secret(
        seed, client_id=int(client.id), credential_id=remote_desktop.id, domain="remote_desktop"
    )
    if not verify_password(rd_secret, remote_desktop.secret_hash):
        raise HTTPException(status_code=409, detail="Enrollment resume-proof matcher ikke credentials")
    rows["remote_desktop"] = remote_desktop.id

    credentials = [EnrollmentCredentialRead(domain=domain, credential_id=rows[domain]) for domain in DOMAIN_NAMES]
    return EnrollmentClaimResponse(
        client_id=int(client.id),
        token_issuer=_canonical_token_issuer(),
        credentials=credentials,
        root_terminal_broker=EnrollmentRootBrokerRead(**_root_terminal_broker(rows["terminal"])),
        system_encryption_key_id=system_key.id,
        status=client.status or "pending",
        name=client.name,
    )


def _resume_existing(
    session: Session,
    *,
    receipt: ClientEnrollmentReceipt,
    seed: bytes,
    resume_proof: str,
    public_key_pem: str,
    system_key_id: str,
) -> EnrollmentClaimResponse:
    if receipt.expires_at < utcnow() and receipt.completed_at is None:
        raise HTTPException(status_code=410, detail="Enrollment resume-vinduet er udløbet")
    if not secrets.compare_digest(receipt.resume_proof_hash, _resume_proof_hash(resume_proof)):
        raise HTTPException(status_code=401, detail="Enrollment resume-proof er ugyldig")
    client = session.get(Client, receipt.client_id)
    system_key = session.exec(
        select(ClientSystemEncryptionKey).where(ClientSystemEncryptionKey.client_id == receipt.client_id)
    ).one_or_none()
    if client is None or system_key is None or system_key.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Enrollment persistence er ufuldstændig")
    if system_key.id != system_key_id or system_key.public_key_pem != public_key_pem:
        raise HTTPException(status_code=409, detail="Enrollment system key matcher ikke oprindelig installation")
    return _credential_response(session, client=client, seed=seed, system_key=system_key)


@router.post("/enrollment/claim", response_model=EnrollmentClaimResponse)
def claim_enrollment_token(
    request: Request,
    data: EnrollmentClaimRequest,
    session: Session = Depends(get_session),
):
    enforce_request_rate_limit(
        request,
        bucket="enrollment-claim",
        max_attempts=10,
        window_seconds=60,
        detail="For mange forsøg med installationskode. Prøv igen senere.",
    )
    install_id = _normalize_install_id(data.install_id)
    seed = _decode_seed(data.credential_seed_b64)
    expected_proof = _derive_resume_proof(seed, install_id)
    if not secrets.compare_digest(expected_proof, data.resume_proof):
        raise HTTPException(status_code=422, detail="resume_proof matcher ikke install_id/credential_seed")
    public_key_pem, system_key_id = _canonical_public_key(data.system_encryption_public_key_pem)

    receipt = session.get(ClientEnrollmentReceipt, install_id)
    if receipt is not None:
        return _resume_existing(
            session,
            receipt=receipt,
            seed=seed,
            resume_proof=data.resume_proof,
            public_key_pem=public_key_pem,
            system_key_id=system_key_id,
        )

    code = (data.enrollment_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Installationskode mangler")
    now = utcnow()
    candidates = session.exec(
        select(EnrollmentToken).where(
            EnrollmentToken.used_at == None,
            EnrollmentToken.revoked_at == None,
            EnrollmentToken.expires_at >= now,
        )
    ).all()
    token = next((candidate for candidate in candidates if verify_password(code, candidate.code_hash)), None)
    if token is None:
        raise HTTPException(status_code=401, detail="Installationskoden er ugyldig, brugt eller udløbet")
    token = session.exec(select(EnrollmentToken).where(EnrollmentToken.id == token.id).with_for_update()).one()
    if token.used_at is not None or token.revoked_at is not None or token.expires_at < now:
        raise HTTPException(status_code=401, detail="Installationskoden er ugyldig, brugt eller udløbet")

    hostname = (data.hostname or "").strip()
    name = (data.name or "").strip() or hostname or "Ny infoskærm"
    locality = (data.locality or "").strip() or None
    client = Client(
        name=name,
        locality=locality,
        wifi_ip_address=data.wifi_ip_address,
        wifi_mac_address=data.wifi_mac_address,
        lan_ip_address=data.lan_ip_address,
        lan_mac_address=data.lan_mac_address,
        machine_id=data.machine_id,
        status="pending",
        isOnline=False,
        last_seen=now,
        sort_order=None,
        kiosk_url=None,
        ubuntu_version=data.ubuntu_version,
        uptime=data.uptime,
        chrome_status="unknown",
        chrome_last_updated=None,
        chrome_color=None,
        chrome_step=None,
        organization_id=token.organization_id,
        state="normal",
        livestream_status="idle",
        livestream_last_segment=None,
        livestream_last_error=None,
        client_secret_hash=None,
        client_secret_created_at=None,
        client_secret_revoked_at=None,
        enrollment_token_id=token.id,
    )
    session.add(client)
    session.flush()
    if client.id is None:
        raise HTTPException(status_code=500, detail="Enrollment kunne ikke oprette client identity")
    client_id = int(client.id)

    receipt = ClientEnrollmentReceipt(
        install_id=install_id,
        client_id=client_id,
        resume_proof_hash=_resume_proof_hash(data.resume_proof),
        created_at=now,
        expires_at=now + timedelta(hours=ENROLLMENT_RESUME_HOURS),
    )
    system_key = ClientSystemEncryptionKey(
        id=system_key_id,
        client_id=client_id,
        algorithm="RSA-OAEP-SHA256",
        public_key_pem=public_key_pem,
        created_at=now,
    )
    session.add(receipt)
    session.add(system_key)

    terminal_identity = TerminalClient(id=client_id, display_name=name, status="disabled", created_at=now)
    rd_identity = RemoteDesktopClient(id=client_id, display_name=name, status="disabled", created_at=now)
    session.add(terminal_identity)
    session.add(rd_identity)
    session.flush()

    credential_ids = {domain: str(uuid.uuid4()) for domain in DOMAIN_NAMES}
    for domain in SHARED_CREDENTIAL_DOMAINS:
        secret = _derive_domain_secret(seed, client_id=client_id, credential_id=credential_ids[domain], domain=domain)
        session.add(ClientDomainCredential(
            id=credential_ids[domain],
            client_id=client_id,
            domain=domain,
            secret_hash=get_password_hash(secret),
            token_version=0,
            created_at=now,
        ))
    livestream_secret = _derive_domain_secret(
        seed, client_id=client_id, credential_id=credential_ids["livestream"], domain="livestream"
    )
    session.add(LivestreamV2Credential(
        id=credential_ids["livestream"],
        client_id=client_id,
        domain="livestream",
        secret_digest=credential_digest(livestream_secret),
        token_version=1,
        created_at=now,
    ))
    terminal_secret = _derive_domain_secret(
        seed, client_id=client_id, credential_id=credential_ids["terminal"], domain="terminal"
    )
    session.add(TerminalCredential(
        id=credential_ids["terminal"],
        client_id=client_id,
        secret_hash=get_password_hash(terminal_secret),
        token_version=0,
        created_at=now,
    ))
    rd_secret = _derive_domain_secret(
        seed, client_id=client_id, credential_id=credential_ids["remote_desktop"], domain="remote_desktop"
    )
    session.add(RemoteDesktopCredential(
        id=credential_ids["remote_desktop"],
        client_id=client_id,
        secret_hash=get_password_hash(rd_secret),
        token_version=0,
        created_at=now,
    ))

    token.used_at = now
    token.used_by_client_id = client_id
    session.add(token)
    add_audit_log(
        session,
        action="client_enrolled",
        request=request,
        entity_type="client",
        entity_id=client_id,
        entity_label=client.name,
        target_organization_id=client.organization_id,
        details={
            "enrollment_token_id": token.id,
            "install_id": install_id,
            "credential_domains": list(DOMAIN_NAMES),
            "machine_id_present": bool(client.machine_id),
            "hostname_present": bool(hostname),
        },
    )
    session.commit()
    session.refresh(client)
    return _credential_response(session, client=client, seed=seed, system_key=system_key)


@router.post("/enrollment/complete")
def complete_enrollment(
    request: Request,
    data: EnrollmentCompleteRequest,
    session: Session = Depends(get_session),
):
    enforce_request_rate_limit(
        request,
        bucket="enrollment-complete",
        max_attempts=20,
        window_seconds=60,
        detail="For mange enrollment-complete forsøg. Prøv igen senere.",
    )
    install_id = _normalize_install_id(data.install_id)
    receipt = session.exec(
        select(ClientEnrollmentReceipt)
        .where(ClientEnrollmentReceipt.install_id == install_id)
        .with_for_update()
    ).one_or_none()
    if receipt is None:
        raise HTTPException(status_code=404, detail="Enrollment receipt blev ikke fundet")
    if not secrets.compare_digest(receipt.resume_proof_hash, _resume_proof_hash(data.resume_proof)):
        raise HTTPException(status_code=401, detail="Enrollment resume-proof er ugyldig")
    if receipt.completed_at is None:
        if receipt.expires_at < utcnow():
            raise HTTPException(status_code=410, detail="Enrollment resume-vinduet er udløbet")
        receipt.completed_at = utcnow()
        session.add(receipt)
        session.commit()
    return {"ok": True, "client_id": receipt.client_id, "install_id": receipt.install_id, "completed_at": receipt.completed_at}
