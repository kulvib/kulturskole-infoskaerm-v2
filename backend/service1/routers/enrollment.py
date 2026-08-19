import secrets
import string
from datetime import timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Body, Request
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from ..db import get_session
from ..audit import add_audit_log
from ..models import Client, EnrollmentToken, Organization, User, utcnow
from ..auth import get_current_superadmin_user, get_password_hash, verify_password
from ..rate_limit import enforce_request_rate_limit

router = APIRouter()


TOKEN_ALPHABET = string.ascii_uppercase + string.digits


def _generate_enrollment_code() -> str:
    # Læsevenlig kode til telefon/mail: CF-ABCD-1234-WXYZ
    parts = []
    for _ in range(3):
        parts.append("".join(secrets.choice(TOKEN_ALPHABET) for _ in range(4)))
    return "CF-" + "-".join(parts)


def _generate_client_secret() -> str:
    return "cf_client_" + secrets.token_urlsafe(32)


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


class EnrollmentClaimRequest(BaseModel):
    enrollment_code: str
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
    client_secret: str
    status: str
    name: str


def _token_to_read(token: EnrollmentToken, session: Optional[Session] = None) -> EnrollmentTokenRead:
    now = utcnow()
    is_used = token.used_at is not None
    is_revoked = token.revoked_at is not None
    # En brugt kode skal ikke efterfølgende vises som udløbet. Status-rækkefølgen er:
    # tilbagekaldt -> brugt -> udløbet -> aktiv.
    is_expired = (not is_used) and (not is_revoked) and token.expires_at < now

    used_client = None
    if session is not None and token.used_by_client_id:
        used_client = session.get(Client, token.used_by_client_id)

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

    # Koden returneres kun her. Den gemmes ikke i klartekst.
    return EnrollmentTokenCreated(
        id=token.id,
        code=code,
        expires_at=token.expires_at.isoformat() + "Z",
        note=token.note,
    )


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
        tokens = [
            t for t in tokens
            if t.used_at is not None
            or (t.revoked_at is None and t.expires_at >= now)
        ]

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
    code = (data.enrollment_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Installationskode mangler")

    now = utcnow()
    # Vi kan ikke slå direkte op på hash pga. bcrypt-salt. Antallet er lavt,
    # så vi scanner kun aktive, ubrugte og ikke-udløbne koder.
    candidates = session.exec(
        select(EnrollmentToken).where(
            EnrollmentToken.used_at == None,
            EnrollmentToken.revoked_at == None,
            EnrollmentToken.expires_at >= now,
        )
    ).all()

    token = None
    for candidate in candidates:
        if verify_password(code, candidate.code_hash):
            token = candidate
            break

    if not token:
        raise HTTPException(status_code=401, detail="Installationskoden er ugyldig, brugt eller udløbet")

    # Lås kun den matchede tokenrække. To samtidige claims kan begge nå gennem
    # bcrypt-verifikationen, men kun én må markere koden som brugt. Efter ventetid
    # på rækkelåsen genvalideres state i den aktuelle PostgreSQL-transaktion.
    token = session.exec(
        select(EnrollmentToken)
        .where(EnrollmentToken.id == token.id)
        .with_for_update()
    ).one()
    if token.used_at is not None or token.revoked_at is not None or token.expires_at < now:
        raise HTTPException(status_code=401, detail="Installationskoden er ugyldig, brugt eller udløbet")

    hostname = (data.hostname or "").strip()
    name = (data.name or "").strip() or hostname or "Ny infoskærm"
    locality = (data.locality or "").strip() or None
    client_secret = _generate_client_secret()

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
        client_secret_hash=get_password_hash(client_secret),
        client_secret_created_at=now,
        client_secret_revoked_at=None,
        enrollment_token_id=token.id,
    )

    session.add(client)
    session.flush()

    token.used_at = now
    token.used_by_client_id = client.id
    session.add(token)
    add_audit_log(
        session,
        action="client_enrolled",
        request=request,
        entity_type="client",
        entity_id=client.id,
        entity_label=client.name,
        target_organization_id=client.organization_id,
        details={
            "enrollment_token_id": token.id,
            "machine_id_present": bool(client.machine_id),
            "hostname_present": bool(hostname),
        },
    )
    session.commit()
    session.refresh(client)

    return EnrollmentClaimResponse(
        client_id=client.id,
        client_secret=client_secret,
        status=client.status or "pending",
        name=client.name,
    )
