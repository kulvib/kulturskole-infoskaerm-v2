"""Cross-cutting lifecycle/decommission primitives for platform Clients and Users.

This module is intentionally small and state-oriented. It does not reach into
router connection registries. Platform lifecycle writes durable authority state;
each isolated domain enforces its own status/credential state on bounded
revalidation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from sqlalchemy import delete
from sqlmodel import Session, select

from .client_activity_models import ClientActivityLease
from .client_domain_models import ClientCommand, ClientDomainCredential, ClientDomainStatus
from .livestream_v2_models import (
    LivestreamV2AgentStatus,
    LivestreamV2Command,
    LivestreamV2Credential,
    LivestreamV2Generation,
    LivestreamV2Viewer,
)
from .models import CalendarMarking, EnrollmentToken, LivestreamViewerLease
from .remote_desktop_session_models import RemoteDesktopSession, RemoteDesktopSessionEvent
from .remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from .terminal_v2_models import (
    RootTerminalGrant,
    TerminalClient,
    TerminalCredential,
    TerminalSession,
    TerminalSessionEvent,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class ClientPurgeStats:
    unlinked_enrollment_tokens: int = 0
    terminal_decommissioned: bool = False
    remote_desktop_decommissioned: bool = False


def decommission_isolated_client_domains(
    session: Session,
    *,
    client_id: int,
    reason: str = "platform_client_permanently_deleted",
) -> tuple[bool, bool]:
    """Permanently disable Terminal/RD identities while retaining domain history."""
    now = utcnow()
    terminal_decommissioned = False
    remote_desktop_decommissioned = False

    terminal_client = session.get(TerminalClient, client_id)
    if terminal_client is not None:
        terminal_client.status = "disabled"
        session.add(terminal_client)
        terminal_decommissioned = True

        credential = session.exec(
            select(TerminalCredential).where(TerminalCredential.client_id == client_id)
        ).first()
        if credential is not None:
            credential.token_version = int(credential.token_version or 0) + 1
            credential.revoked_at = credential.revoked_at or now
            session.add(credential)

        terminal_sessions = session.exec(
            select(TerminalSession).where(
                TerminalSession.client_id == client_id,
                TerminalSession.status.in_(("requested", "authorized", "connected")),
            )
        ).all()
        for row in terminal_sessions:
            row.status = "revoked"
            row.disconnected_at = row.disconnected_at or now
            row.last_activity_at = now
            session.add(row)
            session.add(TerminalSessionEvent(
                id=str(uuid.uuid4()),
                terminal_session_id=row.id,
                event_type="revoked",
                actor_user_id=None,
                credential_id=None,
                created_at=now,
                details={"reason": reason},
            ))

        grants = session.exec(
            select(RootTerminalGrant).where(
                RootTerminalGrant.client_id == client_id,
                RootTerminalGrant.revoked_at.is_(None),
            )
        ).all()
        for grant in grants:
            grant.revoked_at = now
            session.add(grant)

    rd_client = session.get(RemoteDesktopClient, client_id)
    if rd_client is not None:
        rd_client.status = "disabled"
        session.add(rd_client)
        remote_desktop_decommissioned = True

        credential = session.exec(
            select(RemoteDesktopCredential).where(RemoteDesktopCredential.client_id == client_id)
        ).first()
        if credential is not None:
            credential.token_version = int(credential.token_version or 0) + 1
            credential.revoked_at = credential.revoked_at or now
            session.add(credential)

        rd_sessions = session.exec(
            select(RemoteDesktopSession).where(
                RemoteDesktopSession.client_id == client_id,
                RemoteDesktopSession.status.in_(("requested", "authorized", "connected")),
            )
        ).all()
        for row in rd_sessions:
            row.status = "revoked"
            row.disconnected_at = row.disconnected_at or now
            row.last_activity_at = now
            row.close_reason = reason
            session.add(row)
            session.add(RemoteDesktopSessionEvent(
                id=str(uuid.uuid4()),
                remote_desktop_session_id=row.id,
                event_type="revoked",
                actor_user_id=None,
                credential_id=None,
                created_at=now,
                details={"reason": reason},
            ))

    return terminal_decommissioned, remote_desktop_decommissioned


def delete_platform_client_state(session: Session, *, client_id: int) -> int:
    """Delete platform-owned child state in FK-safe order; keep isolated domain history."""
    # Shared/browser presence first.
    session.exec(delete(ClientActivityLease).where(ClientActivityLease.client_id == client_id))
    session.exec(delete(LivestreamViewerLease).where(LivestreamViewerLease.client_id == client_id))

    # Livestream v2 is platform-Client-owned. All tables point directly at client.id.
    session.exec(delete(LivestreamV2Viewer).where(LivestreamV2Viewer.client_id == client_id))
    session.exec(delete(LivestreamV2Generation).where(LivestreamV2Generation.client_id == client_id))
    session.exec(delete(LivestreamV2AgentStatus).where(LivestreamV2AgentStatus.client_id == client_id))
    session.exec(delete(LivestreamV2Command).where(LivestreamV2Command.client_id == client_id))
    session.exec(delete(LivestreamV2Credential).where(LivestreamV2Credential.client_id == client_id))

    # Shared Display/Status/System status/commands reference credentials; delete them first.
    session.exec(delete(ClientDomainStatus).where(ClientDomainStatus.client_id == client_id))
    session.exec(delete(ClientCommand).where(ClientCommand.client_id == client_id))
    session.exec(delete(ClientDomainCredential).where(ClientDomainCredential.client_id == client_id))

    session.exec(delete(CalendarMarking).where(CalendarMarking.client_id == client_id))

    enrollment_tokens = session.exec(
        select(EnrollmentToken).where(EnrollmentToken.used_by_client_id == client_id)
    ).all()
    for token in enrollment_tokens:
        token.used_by_client_id = None
        session.add(token)
    return len(enrollment_tokens)


def prepare_client_for_permanent_delete(
    session: Session,
    *,
    client_id: int,
    reason: str = "platform_client_permanently_deleted",
) -> ClientPurgeStats:
    """Decommission isolated domains and clear platform-owned FK children."""
    terminal_disabled, rd_disabled = decommission_isolated_client_domains(
        session, client_id=client_id, reason=reason
    )
    unlinked = delete_platform_client_state(session, client_id=client_id)
    return ClientPurgeStats(
        unlinked_enrollment_tokens=unlinked,
        terminal_decommissioned=terminal_disabled,
        remote_desktop_decommissioned=rd_disabled,
    )
