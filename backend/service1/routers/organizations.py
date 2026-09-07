from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlmodel import select
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from typing import List, Dict, Any, Optional
import os

from ..db import get_session
from ..audit import add_audit_log
from ..lifecycle import prepare_client_for_permanent_delete
from ..models import (
    Organization,
    Client,
    CalendarMarking,
    User,
    OrganizationSeasonTimes,
    OrganizationLogo,
    EnrollmentToken,
    utcnow,
    OrganizationCreate,
    OrganizationRead,
    OrganizationTimesUpdate,
    OrganizationSeasonTimesReplace,
    OrganizationTimesRead,
    OrganizationNameUpdate,
)
from ..auth import get_current_user, get_current_admin_user, _revoke_all_user_refresh_tokens
from ..season_service import (
    DAY_KEYS,
    SeasonValidationError,
    apply_standard_times_to_season_calendar,
    build_season_calendar,
    current_and_next_seasons,
    ensure_organization_season_times,
    is_off_day,
    normalize_day_times,
    season_dates,
    validate_supported_season,
)

router = APIRouter()

MAX_ORGANIZATION_LOGO_BYTES = int(os.getenv("ORGANIZATION_LOGO_MAX_BYTES", "1000000"))

def _normalize_day_times(value: Any) -> Dict[str, Dict[str, str]]:
    try:
        return normalize_day_times(value)
    except SeasonValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _is_off_day(pair: Dict[str, Any]) -> bool:
    return is_off_day(pair)


def _day_key_for_date(value) -> str:
    return DAY_KEYS[value.weekday()]


def _day_times_from_object(obj) -> Dict[str, Dict[str, str]]:
    return _normalize_day_times(getattr(obj, "day_times", None) if obj else None)


def _times_payload(
    *,
    organization_id: int,
    season: Optional[str] = None,
    day_times: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "organization_id": organization_id,
        "season": season,
        "day_times": day_times,
    }


def _organization_logo_url(organization_id: Optional[int]) -> Optional[str]:
    if organization_id is None:
        return None
    return f"/api/organizations/{organization_id}/logo"


def _organization_dict(obj, logo: Optional[OrganizationLogo] = None):
    """Returnér et Organization-objekt som organization-kompatibel dict uden logo-binary."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        data = dict(obj)
    else:
        try:
            data = obj.model_dump()
        except Exception:
            data = {
                "id": getattr(obj, "id", None),
                "name": getattr(obj, "name", None),
                "day_times": getattr(obj, "day_times", None),
            }
    organization_id = data.get("id")
    data["organization_id"] = organization_id
    data["day_times"] = _normalize_day_times(data.get("day_times"))
    data["has_logo"] = bool(logo)
    data["logo_content_type"] = getattr(logo, "content_type", None) if logo else None
    data["logo_updated_at"] = getattr(logo, "uploaded_at", None) if logo else None
    data["logo_url"] = _organization_logo_url(organization_id) if logo else None
    return data


def _logo_meta_map(session, organization_ids: list[int]) -> dict[int, OrganizationLogo]:
    if not organization_ids:
        return {}
    logos = session.exec(
        select(OrganizationLogo).where(OrganizationLogo.organization_id.in_(organization_ids))
    ).all()
    return {logo.organization_id: logo for logo in logos}


def _content_type_without_params(content_type: Optional[str]) -> str:
    return str(content_type or "").split(";", 1)[0].strip().lower()



def _validate_logo_upload(file: UploadFile, raw: bytes) -> tuple[str, bytes, str]:
    filename = os.path.basename(file.filename or "logo.png").strip() or "logo.png"
    ext = os.path.splitext(filename)[1].lower()
    content_type = _content_type_without_params(file.content_type)

    if len(raw) > MAX_ORGANIZATION_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="Logo må højst være 1 MB")
    if not raw:
        raise HTTPException(status_code=400, detail="Logo-filen er tom")
    if ext != ".png" or content_type != "image/png":
        raise HTTPException(status_code=400, detail="Logo skal være en PNG-fil")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="Logo-filen er ikke en gyldig PNG-fil")

    return "image/png", raw, filename

def _client_dict(obj):
    if isinstance(obj, dict):
        data = dict(obj)
    else:
        try:
            data = obj.model_dump()
        except Exception:
            data = dict(getattr(obj, "__dict__", {}) or {})
    data["organization_id"] = data.get("organization_id")
    return data


def _require_organization_read_access(user, organization_id: int):
    if getattr(user, "is_superadmin", False):
        return
    if getattr(user, "role", None) == "viewer":
        return
    if getattr(user, "organization_id", None) == organization_id:
        return
    raise HTTPException(status_code=403, detail="Du har kun adgang til din egen organisation")


def _require_organization_admin_write_access(user, organization_id: int):
    if getattr(user, "is_superadmin", False):
        return
    if getattr(user, "role", None) == "admin" and getattr(user, "organization_id", None) == organization_id:
        return
    raise HTTPException(status_code=403, detail="Kun superadministrator eller administrator for egen organisation kan ændre dette")


def _require_organization_superadmin_write(user):
    if not getattr(user, "is_superadmin", False):
        raise HTTPException(status_code=403, detail="Denne handling kræver superadministrator")


# Bagudkompatibelt alias til rene læse-endpoints.
def _require_organization_access(user, organization_id: int):
    return _require_organization_read_access(user, organization_id)


def _validate_season(season: str) -> str:
    try:
        return validate_supported_season(season)
    except SeasonValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_season_year_dates(season: str):
    return season_dates(_validate_season(season))


@router.get("/organizations/", response_model=List[OrganizationRead])
def get_organizations(session=Depends(get_session), user=Depends(get_current_user)):
    if user.is_superadmin or getattr(user, "role", None) == "viewer":
        items = session.exec(select(Organization)).all()
    elif user.organization_id:
        organization = session.get(Organization, user.organization_id)
        items = [organization] if organization else []
    else:
        items = []
    logo_map = _logo_meta_map(session, [item.id for item in items if item and item.id is not None])
    return [_organization_dict(item, logo_map.get(item.id)) for item in items]


@router.get("/organizations/season-summary")
def get_organization_season_summary(session=Depends(get_session), user=Depends(get_current_user)):
    """
    Returnerer hvilke organisationer der har data i hver sæson.

    Data betyder enten konkret klientkalender (CalendarMarking) eller
    organisations-standardtider for sæsonen (OrganizationSeasonTimes).
    Dermed forsvinder en sæson ikke fra UI'et blot fordi den endnu ikke er
    pushet ud til klienter.
    """
    if user.is_superadmin or getattr(user, "role", None) == "viewer":
        allowed_organization_ids = None
    elif user.organization_id:
        allowed_organization_ids = {user.organization_id}
    else:
        allowed_organization_ids = set()

    organizations = session.exec(select(Organization)).all()
    organization_map = {
        item.id: item.name
        for item in organizations
        if item.id is not None and (allowed_organization_ids is None or item.id in allowed_organization_ids)
    }

    clients = session.exec(select(Client)).all()
    client_organization_map = {
        c.id: c.organization_id
        for c in clients
        if c.id is not None
        and c.organization_id
        and (allowed_organization_ids is None or c.organization_id in allowed_organization_ids)
    }

    season_organizations: dict[str, set] = {}

    def add(season: Any, organization_id: Any) -> None:
        if not season or not organization_id or organization_id not in organization_map:
            return
        season = str(season)
        if season not in season_organizations:
            season_organizations[season] = set()
        season_organizations[season].add(organization_id)

    for row in session.exec(select(OrganizationSeasonTimes)).all():
        if allowed_organization_ids is not None and row.organization_id not in allowed_organization_ids:
            continue
        add(row.season, row.organization_id)

    for marking in session.exec(select(CalendarMarking)).all():
        add(marking.season, client_organization_map.get(marking.client_id))

    def sort_key(value: str) -> int:
        try:
            return int(str(value).split("/")[0])
        except Exception:
            return 999999

    result = {}
    for season in sorted(season_organizations.keys(), key=sort_key):
        result[season] = [
            {"id": oid, "organization_id": oid, "name": organization_map[oid]}
            for oid in sorted(season_organizations[season], key=lambda item: organization_map.get(item, ""))
            if oid in organization_map
        ]

    return result


@router.post("/organizations/", response_model=OrganizationRead)
def create_organization(
    request: Request,
    organization: OrganizationCreate,
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    if not admin.is_superadmin:
        raise HTTPException(status_code=403, detail="Kun superadmin må oprette organisationer")
    existing = session.exec(select(Organization).where(Organization.name == organization.name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Organisationen findes allerede")

    new_organization = Organization(
        name=organization.name,
        day_times=_normalize_day_times(getattr(organization, "day_times", None)),
    )
    session.add(new_organization)
    session.flush()
    ensure_organization_season_times(
        session,
        new_organization,
        current_and_next_seasons(),
    )
    add_audit_log(
        session,
        action="organization_created",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=new_organization.id,
        entity_label=new_organization.name,
    )
    session.commit()
    session.refresh(new_organization)
    return _organization_dict(new_organization)


@router.get("/organizations/{organization_id}/clients/")
def get_clients_for_organization(
    organization_id: int,
    session=Depends(get_session),
    user=Depends(get_current_user),
):
    _require_organization_access(user, organization_id)
    clients = session.exec(
        select(Client).where(
            Client.organization_id == organization_id,
            Client.deleted_at == None,
        )
    ).all()
    return [_client_dict(client) for client in clients]


@router.get("/organizations/{organization_id}/logo")
def get_organization_logo(
    organization_id: int,
    session=Depends(get_session),
    user=Depends(get_current_user),
):
    _require_organization_access(user, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")
    logo = session.get(OrganizationLogo, organization_id)
    if not logo:
        raise HTTPException(status_code=404, detail="Logo ikke fundet")

    headers = {
        "Cache-Control": "private, max-age=300",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": 'inline; filename="organization-logo.png"',
    }
    return Response(content=logo.data, media_type=logo.content_type, headers=headers)


@router.put("/organizations/{organization_id}/logo", response_model=OrganizationRead)
async def upload_organization_logo(
    request: Request,
    organization_id: int,
    file: UploadFile = File(...),
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    _require_organization_admin_write_access(admin, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")

    try:
        raw = await file.read(MAX_ORGANIZATION_LOGO_BYTES + 1)
        content_type, logo_data, filename = _validate_logo_upload(file, raw)
    finally:
        await file.close()

    logo = session.get(OrganizationLogo, organization_id)
    if not logo:
        logo = OrganizationLogo(organization_id=organization_id, filename=filename, content_type=content_type, data=logo_data, size_bytes=len(logo_data))
    else:
        logo.filename = filename
        logo.content_type = content_type
        logo.data = logo_data
        logo.size_bytes = len(logo_data)
    logo.uploaded_at = utcnow()
    logo.uploaded_by_user_id = getattr(admin, "id", None)

    session.add(logo)
    add_audit_log(
        session,
        action="organization_logo_updated",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=organization.id,
        entity_label=organization.name,
        details={"filename": filename, "size_bytes": len(logo_data), "content_type": content_type},
    )
    session.commit()
    session.refresh(logo)
    session.refresh(organization)
    return _organization_dict(organization, logo)


@router.delete("/organizations/{organization_id}/logo", response_model=OrganizationRead)
def delete_organization_logo(
    request: Request,
    organization_id: int,
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    _require_organization_admin_write_access(admin, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")
    logo = session.get(OrganizationLogo, organization_id)
    logo_existed = logo is not None
    if logo:
        session.delete(logo)
    add_audit_log(
        session,
        action="organization_logo_deleted",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=organization.id,
        entity_label=organization.name,
        details={"logo_existed": logo_existed},
    )
    session.commit()
    return _organization_dict(organization)


@router.delete("/organizations/{organization_id}/", status_code=204)
def delete_organization(
    request: Request,
    organization_id: int,
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    if not admin.is_superadmin:
        raise HTTPException(status_code=403, detail="Kun superadmin må slette organisationer")
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")

    # Organisation-sletning er en permanent oprydning. Ryd eksplicit alle kendte
    # afhængigheder først, så databasen ikke ender i FK-fejl/500.
    clients = session.exec(select(Client).where(Client.organization_id == organization_id)).all()
    client_ids = [client.id for client in clients if client.id is not None]

    organization_logo = session.get(OrganizationLogo, organization_id)
    if organization_logo:
        session.delete(organization_logo)

    enrollment_tokens = session.exec(
        select(EnrollmentToken).where(EnrollmentToken.organization_id == organization_id)
    ).all()

    # EnrollmentToken og Client kan pege på hinanden via used_by_client_id og
    # enrollment_token_id. Bryd de relationer før klienter/tokens slettes.
    if client_ids:
        tokens_for_deleted_clients = session.exec(
            select(EnrollmentToken).where(EnrollmentToken.used_by_client_id.in_(client_ids))
        ).all()
    else:
        tokens_for_deleted_clients = []

    for token in [*enrollment_tokens, *tokens_for_deleted_clients]:
        token.used_by_client_id = None
        session.add(token)

    for client in clients:
        client.enrollment_token_id = None
        session.add(client)

    session.flush()

    decommissioned_terminal = 0
    decommissioned_remote_desktop = 0
    for client in clients:
        stats = prepare_client_for_permanent_delete(
            session,
            client_id=int(client.id),
            reason="organization_deleted",
        )
        decommissioned_terminal += int(stats.terminal_decommissioned)
        decommissioned_remote_desktop += int(stats.remote_desktop_decommissioned)
        session.delete(client)

    # Installationskoder for en slettet organisation skal ikke bevares. De kan
    # ellers blokere sletningen via organization_id foreign key.
    seen_token_ids = set()
    for token in [*enrollment_tokens, *tokens_for_deleted_clients]:
        token_id = getattr(token, "id", None)
        if token_id in seen_token_ids:
            continue
        seen_token_ids.add(token_id)
        if token.organization_id == organization_id:
            session.delete(token)

    organization_users = session.exec(select(User).where(User.organization_id == organization_id)).all()
    for user in organization_users:
        # An organization-scoped role without an organization is invalid. Park
        # the account safely and revoke its browser login families before detach.
        user.is_active = False
        user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
        user.password_reset_token_hash = None
        user.password_reset_expires_at = None
        user.must_change_password = True
        _revoke_all_user_refresh_tokens(session, int(user.id))
        user.organization_id = None
        session.add(user)

    # Ryd organisationens sæsontider med direkte SQL før selve organisationen slettes.
    # På Neon findes FK'en historisk som schoolseasontimes_school_id_fkey på
    # organizationseasontimes.organization_id. Direkte DELETE undgår at SQLAlchemy
    # unit-of-work kan sende organization DELETE før season-times DELETE.
    session.execute(
        text("DELETE FROM organizationseasontimes WHERE organization_id = :organization_id"),
        {"organization_id": organization_id},
    )
    session.flush()

    add_audit_log(
        session,
        action="organization_deleted",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=organization.id,
        entity_label=organization.name,
        severity="critical",
        is_critical=True,
        details={
            "deleted_clients": len(clients),
            "deleted_enrollment_tokens": len(enrollment_tokens),
            "deactivated_detached_users": len(organization_users),
            "terminal_clients_decommissioned": decommissioned_terminal,
            "remote_desktop_clients_decommissioned": decommissioned_remote_desktop,
        },
    )
    session.delete(organization)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Organisationen kunne ikke slettes, fordi der stadig findes relaterede databaseposter. Send Render-loggen, så relationen kan ryddes korrekt.",
        ) from exc


@router.patch("/organizations/{organization_id}/times", response_model=OrganizationRead)
def update_organization_times(
    request: Request,
    organization_id: int,
    times: OrganizationTimesUpdate,
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    _require_organization_admin_write_access(admin, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")

    organization.day_times = _normalize_day_times(times.day_times)

    session.add(organization)
    add_audit_log(
        session,
        action="organization_times_updated",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=organization.id,
        entity_label=organization.name,
    )
    session.commit()
    session.refresh(organization)
    return _organization_dict(organization, session.get(OrganizationLogo, organization_id))


@router.get("/organizations/{organization_id}/times", response_model=OrganizationTimesRead)
def get_organization_times(organization_id: int, session=Depends(get_session), user=Depends(get_current_user)):
    _require_organization_access(user, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")
    return _times_payload(organization_id=organization_id, day_times=_day_times_from_object(organization))


@router.get("/organizations/{organization_id}/season-times/{season:path}", response_model=OrganizationTimesRead)
def get_organization_season_times(
    organization_id: int,
    season: str,
    session=Depends(get_session),
    user=Depends(get_current_user),
):
    _validate_season(season)
    _require_organization_access(user, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")
    season_times = session.exec(
        select(OrganizationSeasonTimes).where(
            OrganizationSeasonTimes.organization_id == organization_id,
            OrganizationSeasonTimes.season == season,
        )
    ).first()
    day_times = _day_times_from_object(season_times) if season_times else _day_times_from_object(organization)
    return _times_payload(organization_id=organization_id, season=season, day_times=day_times)


@router.patch("/organizations/{organization_id}/season-times/{season:path}", response_model=OrganizationTimesRead)
def update_organization_season_times(
    request: Request,
    organization_id: int,
    season: str,
    times: OrganizationTimesUpdate,
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    _validate_season(season)
    _require_organization_admin_write_access(admin, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")
    season_times = session.exec(
        select(OrganizationSeasonTimes).where(
            OrganizationSeasonTimes.organization_id == organization_id,
            OrganizationSeasonTimes.season == season,
        )
    ).first()

    if not season_times:
        season_times = OrganizationSeasonTimes(
            organization_id=organization_id,
            season=season,
        )

    season_times.day_times = _normalize_day_times(times.day_times)

    session.add(season_times)
    add_audit_log(
        session,
        action="organization_season_times_updated",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=organization.id,
        entity_label=organization.name,
        details={"season": season},
    )
    session.commit()
    session.refresh(season_times)
    return _times_payload(organization_id=organization_id, season=season, day_times=_day_times_from_object(season_times))


@router.post("/organizations/{organization_id}/apply-season-times/{season:path}")
def apply_organization_season_times(
    request: Request,
    organization_id: int,
    season: str,
    times: OrganizationTimesUpdate,
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    season = _validate_season(season)
    _require_organization_admin_write_access(admin, organization_id)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")

    season_times = session.exec(
        select(OrganizationSeasonTimes).where(
            OrganizationSeasonTimes.organization_id == organization_id,
            OrganizationSeasonTimes.season == season,
        )
    ).first()
    old_day_times = (
        _day_times_from_object(season_times)
        if season_times
        else _day_times_from_object(organization)
    )
    new_day_times = _normalize_day_times(times.day_times)
    if not season_times:
        season_times = OrganizationSeasonTimes(
            organization_id=organization_id,
            season=season,
        )
    season_times.day_times = new_day_times
    session.add(season_times)

    total_days = len(_get_season_year_dates(season))
    clients = session.exec(
        select(Client).where(
            Client.organization_id == organization_id,
            Client.status == "approved",
            Client.deleted_at == None,
        )
    ).all()

    updated_clients: list[int] = []
    created_calendars = 0
    changed_days = 0
    preserved_manual_days = 0
    filled_days = 0
    for client in clients:
        existing = session.exec(
            select(CalendarMarking).where(
                CalendarMarking.season == season,
                CalendarMarking.client_id == client.id,
            )
        ).first()
        if existing is None:
            session.add(
                CalendarMarking(
                    season=season,
                    client_id=client.id,
                    markings=build_season_calendar(season, new_day_times),
                )
            )
            created_calendars += 1
            changed_days += total_days
        else:
            updated_markings, changed, preserved, filled = apply_standard_times_to_season_calendar(
                existing.markings,
                season=season,
                old_times=old_day_times,
                new_times=new_day_times,
            )
            existing.markings = updated_markings
            session.add(existing)
            changed_days += changed
            preserved_manual_days += preserved
            filled_days += filled
        updated_clients.append(client.id)

    add_audit_log(
        session,
        action="organization_season_times_applied_safely",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=organization.id,
        entity_label=organization.name,
        details={
            "season": season,
            "updated_clients": len(updated_clients),
            "created_calendars": created_calendars,
            "changed_days": changed_days,
            "preserved_manual_days": preserved_manual_days,
            "filled_days": filled_days,
            "total_days": total_days,
            "day_times": new_day_times,
        },
    )
    session.commit()
    return {
        "ok": True,
        "organization_id": organization_id,
        "season": season,
        "updated_clients": updated_clients,
        "created_calendars": created_calendars,
        "changed_days": changed_days,
        "preserved_manual_days": preserved_manual_days,
        "filled_days": filled_days,
        "total_days": total_days,
        "day_times": new_day_times,
    }


@router.post("/organizations/{organization_id}/replace-season-calendars/{season:path}")
def replace_organization_season_calendars(
    request: Request,
    organization_id: int,
    season: str,
    payload: OrganizationSeasonTimesReplace,
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    season = _validate_season(season)
    _require_organization_admin_write_access(admin, organization_id)
    if str(payload.confirmation or "").strip().upper() != "OVERSKRIV":
        raise HTTPException(status_code=400, detail="Skriv OVERSKRIV for at bekræfte handlingen")

    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")

    new_day_times = _normalize_day_times(payload.day_times)
    season_times = session.exec(
        select(OrganizationSeasonTimes).where(
            OrganizationSeasonTimes.organization_id == organization_id,
            OrganizationSeasonTimes.season == season,
        )
    ).first()
    if not season_times:
        season_times = OrganizationSeasonTimes(
            organization_id=organization_id,
            season=season,
        )
    season_times.day_times = new_day_times
    session.add(season_times)

    replacement_calendar = build_season_calendar(season, new_day_times)
    clients = session.exec(
        select(Client).where(
            Client.organization_id == organization_id,
            Client.status == "approved",
            Client.deleted_at == None,
        )
    ).all()

    updated_clients: list[int] = []
    created_calendars = 0
    replaced_calendars = 0
    for client in clients:
        existing = session.exec(
            select(CalendarMarking).where(
                CalendarMarking.season == season,
                CalendarMarking.client_id == client.id,
            )
        ).first()
        if existing is None:
            existing = CalendarMarking(
                season=season,
                client_id=client.id,
                markings={key: dict(value) for key, value in replacement_calendar.items()},
            )
            created_calendars += 1
        else:
            existing.markings = {key: dict(value) for key, value in replacement_calendar.items()}
            replaced_calendars += 1
        session.add(existing)
        updated_clients.append(client.id)

    add_audit_log(
        session,
        action="organization_season_calendars_replaced",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=organization.id,
        entity_label=organization.name,
        severity="critical",
        is_critical=True,
        details={
            "season": season,
            "updated_clients": len(updated_clients),
            "created_calendars": created_calendars,
            "replaced_calendars": replaced_calendars,
            "total_days": len(replacement_calendar),
            "day_times": new_day_times,
        },
    )
    session.commit()
    return {
        "ok": True,
        "organization_id": organization_id,
        "season": season,
        "updated_clients": updated_clients,
        "created_calendars": created_calendars,
        "replaced_calendars": replaced_calendars,
        "total_days": len(replacement_calendar),
        "day_times": new_day_times,
    }


@router.patch("/organizations/{organization_id}/", response_model=OrganizationRead)
def update_organization_name(
    request: Request,
    organization_id: int,
    update: OrganizationNameUpdate,
    session=Depends(get_session),
    admin=Depends(get_current_admin_user),
):
    _require_organization_superadmin_write(admin)
    organization = session.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organisation ikke fundet")
    existing = session.exec(select(Organization).where(Organization.name == update.name)).first()
    if existing and existing.id != organization_id:
        raise HTTPException(status_code=400, detail="Organisationsnavnet findes allerede")
    name_before = organization.name
    organization.name = update.name
    session.add(organization)
    add_audit_log(
        session,
        action="organization_name_changed",
        request=request,
        actor=admin,
        entity_type="organization",
        entity_id=organization.id,
        entity_label=organization.name,
        details={"name_before": name_before, "name_after": organization.name},
    )
    session.commit()
    session.refresh(organization)
    return _organization_dict(organization, session.get(OrganizationLogo, organization_id))
