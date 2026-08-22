from sqlmodel import SQLModel, Field, Column, JSON
from sqlalchemy import CheckConstraint, Enum as SAEnum, Index, LargeBinary, Text, UniqueConstraint
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from enum import Enum
from pydantic import ConfigDict
from sqlalchemy.dialects.postgresql import JSONB


def _jsonb_type():
    """JSON locally, JSONB in PostgreSQL/Neon."""
    return JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _nullable_text_field(default: Optional[str] = None):
    """Map Python strings to the legacy PostgreSQL TEXT columns exactly."""
    return Field(default=default, sa_column=Column(Text, nullable=True))


DEFAULT_DAY_TIMES = {
    "monday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "tuesday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "wednesday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "thursday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "friday": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
    "saturday": {"status": "off"},
    "sunday": {"status": "off"},
}


def default_day_times() -> Dict[str, Dict[str, str]]:
    return {day: dict(times) for day, times in DEFAULT_DAY_TIMES.items()}


class ChromeAction(str, Enum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    SHUTDOWN = "shutdown"
    SLEEP = "sleep"
    WAKEUP = "wakeup"
    NONE = "none"
    LIVESTREAM_START = "livestream_start"
    LIVESTREAM_STOP = "livestream_stop"
    OS_UPDATE = "os_update"
    CLIENTFLOW_UPDATE = "clientflow_update"
    RESET_BROWSER = "reset_browser"


class Organization(SQLModel, table=True):
    __tablename__ = "organization"
    __table_args__ = (Index("ix_school_name", "name", unique=True),)
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    day_times: Dict[str, Dict[str, str]] = Field(
        default_factory=default_day_times,
        sa_column=Column(_jsonb_type(), nullable=False),
    )

    @property
    def organization_id(self):
        return self.id


class OrganizationSeasonTimes(SQLModel, table=True):
    __tablename__ = "organizationseasontimes"
    __table_args__ = (
        UniqueConstraint("organization_id", "season", name="organizationseasontimes_org_season_unique"),
        Index("ix_schoolseasontimes_school_id", "organization_id"),
        Index("ix_schoolseasontimes_season", "season"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id")
    season: str = Field(sa_column=Column(Text, nullable=False))
    day_times: Dict[str, Dict[str, str]] = Field(
        default_factory=default_day_times,
        sa_column=Column(_jsonb_type(), nullable=False),
    )


class OrganizationLogo(SQLModel, table=True):
    __tablename__ = "organizationlogo"
    organization_id: int = Field(primary_key=True, foreign_key="organization.id")
    filename: str
    content_type: str = Field(index=True)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    size_bytes: int
    uploaded_at: datetime = Field(default_factory=utcnow, nullable=False)
    uploaded_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

class User(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "role IN ('superadmin', 'admin', 'bruger', 'viewer')",
            name="users_role_check",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str
    hashed_password: str
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    role: str = "bruger"
    is_active: bool = True
    must_change_password: bool = True
    token_version: int = Field(default=0, nullable=False)
    password_reset_token_hash: Optional[str] = Field(default=None, index=True)
    password_reset_expires_at: Optional[datetime] = Field(default=None, index=True)
    last_login_at: Optional[datetime] = Field(default=None, index=True)
    last_login_ip: Optional[str] = None
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id")


    full_name: Optional[str] = None
    remarks: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    email: str = Field(max_length=255)

    @property
    def is_admin(self):
        return self.role in ("admin", "superadmin")

    @property
    def is_superadmin(self):
        return self.role == "superadmin"

    @property
    def is_viewer(self):
        return self.role == "viewer"


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True, nullable=False)
    token_hash: str = Field(index=True, unique=True, max_length=64, nullable=False)
    expires_at: datetime = Field(index=True, nullable=False)
    session_expires_at: Optional[datetime] = Field(default=None, index=True)
    revoked_at: Optional[datetime] = Field(default=None, index=True)
    created_ip: Optional[str] = Field(default=None, max_length=45)
    user_agent: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_request_id", "request_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    action: str = Field(index=True, max_length=100)
    status: str = Field(default="success", max_length=40)

    # Snapshot-felter uden ForeignKey: loggen skal stadig være læsbar, hvis
    # brugere senere ændres eller slettes permanent.
    actor_user_id: Optional[int] = Field(default=None, index=True)
    actor_username: Optional[str] = None
    actor_role: Optional[str] = None
    actor_organization_id: Optional[int] = None

    target_user_id: Optional[int] = Field(default=None, index=True)
    target_username: Optional[str] = None
    target_organization_id: Optional[int] = None

    entity_type: Optional[str] = Field(default=None, index=True)
    entity_id: Optional[int] = Field(default=None, index=True)
    entity_label: Optional[str] = None

    request_id: Optional[str] = Field(default=None, max_length=64)
    request_ip: Optional[str] = None
    user_agent: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    severity: str = Field(default="info", index=True, max_length=20)
    is_critical: bool = Field(default=False, index=True)
    retention_days: Optional[int] = None
    retain_until: Optional[datetime] = Field(default=None, index=True)

    details: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON, nullable=True))


class ClientBase(SQLModel):
    name: str
    locality: Optional[str] = None
    wifi_ip_address: Optional[str] = None
    wifi_mac_address: Optional[str] = None
    lan_ip_address: Optional[str] = None
    lan_mac_address: Optional[str] = None


class Client(ClientBase, table=True):
    __table_args__ = (
        Index("idx_client_deleted_at", "deleted_at"),
        Index("idx_client_org_deleted_at", "organization_id", "deleted_at"),
        Index("idx_client_sort_order", "sort_order"),
        Index("idx_client_status_deleted_at", "status", "deleted_at"),
        Index("ix_client_last_boot_id", "last_boot_id"),
        Index("ix_client_last_power_event_at", "last_power_event_at"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    # Client-secret bruges af nye klienter installeret via enrollment-token.
    # Eksisterende klienter med admin-login virker fortsat bagudkompatibelt.
    client_secret_hash: Optional[str] = _nullable_text_field()
    client_secret_created_at: Optional[datetime] = None
    client_secret_revoked_at: Optional[datetime] = None
    client_token_version: int = Field(default=0, nullable=False)
    enrollment_token_id: Optional[int] = Field(default=None, foreign_key="enrollmenttoken.id")
    machine_id: Optional[str] = _nullable_text_field()
    status: Optional[str] = "pending"
    deleted_at: Optional[datetime] = None
    deleted_by_user_id: Optional[int] = None
    deleted_reason: Optional[str] = _nullable_text_field()
    deleted_previous_status: Optional[str] = _nullable_text_field()
    restored_at: Optional[datetime] = None
    restored_by_user_id: Optional[int] = None
    sort_order: Optional[int] = None
    kiosk_url: Optional[str] = None
    browser_refresh_interval_sec: Optional[int] = Field(default=900)
    ubuntu_version: Optional[str] = None
    uptime: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=utcnow, nullable=False)
    chrome_status: Optional[str] = _nullable_text_field("unknown")
    chrome_last_updated: Optional[datetime] = None
    pending_reboot: Optional[bool] = False
    pending_shutdown: Optional[bool] = False
    chrome_color: Optional[str] = _nullable_text_field()
    # FIX: chrome_step gemmes i DB så backend kan returnere det uden
    # at læse chrome_status.json som kun findes på klient-maskinen.
    chrome_step: Optional[str] = Field(default=None)
    pending_chrome_action: Optional[ChromeAction] = Field(
        default=ChromeAction.NONE,
        sa_column=Column(
            SAEnum(
                ChromeAction,
                name="chromeaction",
                native_enum=False,
                length=20,
            ),
            nullable=True,
        ),
    )
    pending_chrome_action_source: Optional[str] = _nullable_text_field()
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id")


    state: Optional[str] = Field(default="normal", max_length=32)

    # Power/lifecycle-events: state er aktuel driftstilstand, mens disse
    # felter beskriver seneste boot/reboot/shutdown-hændelse.
    last_boot_id: Optional[str] = None
    last_boot_at: Optional[datetime] = None
    last_power_event: Optional[str] = None
    last_power_event_at: Optional[datetime] = None
    last_power_event_source: Optional[str] = None
    last_reboot_started_at: Optional[datetime] = None
    last_shutdown_started_at: Optional[datetime] = None

    livestream_status: Optional[str] = Field(default="idle", max_length=50)
    livestream_viewer_last_seen: Optional[datetime] = None
    livestream_viewer_count: Optional[int] = Field(default=0)
    livestream_desired_state: Optional[str] = Field(default="stopped")
    livestream_stop_reason: Optional[str] = _nullable_text_field()
    livestream_last_segment: Optional[datetime] = None
    livestream_last_error: Optional[str] = _nullable_text_field()
    # Diagnostik/status snapshot fra klienten (bruges i webfrontend til fjernsupport).
    diagnostics_updated_at: Optional[datetime] = None
    system_timezone: Optional[str] = _nullable_text_field()
    ntp_enabled: Optional[bool] = None
    ntp_synchronized: Optional[bool] = None
    client_time_utc: Optional[datetime] = None
    clock_drift_seconds: Optional[float] = None
    time_sync_status: Optional[str] = _nullable_text_field("unknown")
    time_sync_message: Optional[str] = _nullable_text_field()
    active_network_type: Optional[str] = _nullable_text_field()
    active_network_interface: Optional[str] = _nullable_text_field()
    active_network_ip: Optional[str] = _nullable_text_field()
    active_network_mac: Optional[str] = _nullable_text_field()
    service_clientflow_status: Optional[str] = _nullable_text_field()
    service_calendar_status: Optional[str] = _nullable_text_field()
    service_browser_guard_status: Optional[str] = _nullable_text_field()
    service_remote_terminal_status: Optional[str] = _nullable_text_field()
    service_admin_terminal_status: Optional[str] = _nullable_text_field()
    service_remote_desktop_status: Optional[str] = _nullable_text_field()
    service_kiosk_x11_guard_status: Optional[str] = _nullable_text_field()  # legacy/optional; kept for backward compatibility
    service_livestream_status: Optional[str] = _nullable_text_field()
    service_selfupdate_status: Optional[str] = _nullable_text_field()
    service_ubuntu_update_status: Optional[str] = _nullable_text_field()
    service_local_reboot_reporter_status: Optional[str] = _nullable_text_field()
    service_local_shutdown_reporter_status: Optional[str] = _nullable_text_field()
    livestream_process_status: Optional[str] = _nullable_text_field()
    # Fysisk X11/display-opløsning på klienten (fjernstyret fra backend/frontend).
    display_resolution_preset: Optional[str] = _nullable_text_field("auto")
    display_resolution_mode: Optional[str] = _nullable_text_field("auto")  # auto | fixed
    display_resolution_width: Optional[int] = None
    display_resolution_height: Optional[int] = None
    display_resolution_refresh_rate: Optional[float] = None
    display_resolution_rotation: Optional[str] = _nullable_text_field("normal")  # normal | left | right | inverted
    display_resolution_action: Optional[str] = _nullable_text_field()  # detect | apply | None
    display_resolution_updated_at: Optional[datetime] = None
    display_resolution_current_output: Optional[str] = _nullable_text_field()
    display_resolution_current_width: Optional[int] = None
    display_resolution_current_height: Optional[int] = None
    display_resolution_current_refresh_rate: Optional[float] = None
    display_resolution_status: Optional[str] = _nullable_text_field("unknown")  # unknown | pending | detected | applying | applied | error
    display_resolution_error: Optional[str] = _nullable_text_field()
    display_resolution_last_applied_at: Optional[datetime] = None
    # Skærm-detektering fra klienten: alle outputs/modes klienten har fundet.
    display_detected_outputs: Optional[list[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    display_detected_updated_at: Optional[datetime] = None
    ubuntu_updates_available: Optional[int] = Field(default=0)
    pending_os_update: Optional[bool] = Field(default=False)
    # Detaljeret Ubuntu-update telemetry rapporteret af klienten.
    ubuntu_update_status: Optional[str] = _nullable_text_field("ready")
    ubuntu_update_step: Optional[str] = _nullable_text_field()
    ubuntu_update_message: Optional[str] = _nullable_text_field()
    ubuntu_update_error: Optional[str] = _nullable_text_field()
    ubuntu_update_started_at: Optional[datetime] = None
    ubuntu_update_updated_at: Optional[datetime] = None
    ubuntu_update_finished_at: Optional[datetime] = None
    ubuntu_update_progress: Optional[int] = None
    ubuntu_update_package_count: Optional[int] = None
    ubuntu_update_reboot_required: Optional[bool] = None

    # Kiosk lockdown ønsket tilstand + klientrapporteret status. Lockdown må kun ramme kiosk-brugeren.
    desktop_lockdown_enabled: Optional[bool] = Field(default=False)
    desktop_lockdown_status: Optional[str] = _nullable_text_field("unknown")
    desktop_lockdown_message: Optional[str] = _nullable_text_field()
    desktop_lockdown_updated_at: Optional[datetime] = None
    desktop_lockdown_last_applied_at: Optional[datetime] = None

    # ClientFlow self-update status (backend-triggeret klientopdatering).
    client_version: Optional[str] = _nullable_text_field()
    client_version_patch: Optional[str] = _nullable_text_field()
    client_version_updated_at: Optional[datetime] = None
    client_update_status: Optional[str] = _nullable_text_field("ready")
    client_update_message: Optional[str] = _nullable_text_field()
    client_update_requested_at: Optional[datetime] = None
    client_update_started_at: Optional[datetime] = None
    client_update_finished_at: Optional[datetime] = None
    client_update_error: Optional[str] = _nullable_text_field()
    client_update_target_version: Optional[str] = _nullable_text_field("latest")
    client_update_target_release_sequence: Optional[int] = None
    client_update_deployment_sequence: int = Field(default=0, nullable=False)
    client_update_applied_deployment_sequence: int = Field(default=0, nullable=False)
    client_update_allow_downgrade: bool = Field(default=False, nullable=False)
    client_update_reason: Optional[str] = _nullable_text_field()

    # Lokal klientstyring (ikke browser/kiosk-flow).
    # local_management_secret gemmer kun krypteret one-time secret og må ikke eksponeres i ClientRead.
    local_management_action: Optional[str] = _nullable_text_field()
    local_management_request_id: Optional[str] = _nullable_text_field()
    local_management_desired_hostname: Optional[str] = _nullable_text_field()
    local_management_secret: Optional[str] = _nullable_text_field()
    local_management_status: Optional[str] = _nullable_text_field("ready")
    local_management_message: Optional[str] = _nullable_text_field()
    local_management_requested_at: Optional[datetime] = None
    local_management_started_at: Optional[datetime] = None
    local_management_finished_at: Optional[datetime] = None
    local_management_error: Optional[str] = _nullable_text_field()


class ClientDomainPresenceRead(SQLModel):
    domain: str
    is_online: bool = False
    reason: str = "not_evaluated"
    observed_state: Optional[str] = None
    reported_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    agent_version: Optional[str] = None
    boot_id: Optional[str] = None


def _default_domain_presence(domain: str) -> ClientDomainPresenceRead:
    return ClientDomainPresenceRead(domain=domain)


class ClientPresenceRead(SQLModel):
    is_online: bool = False
    status: ClientDomainPresenceRead = Field(default_factory=lambda: _default_domain_presence("status"))
    display: ClientDomainPresenceRead = Field(default_factory=lambda: _default_domain_presence("display"))
    system: ClientDomainPresenceRead = Field(default_factory=lambda: _default_domain_presence("system"))


class ClientRead(ClientBase):
    model_config = ConfigDict(from_attributes=True)

    """
    Sikker API-repræsentation af en Client.

    Bevidst udeladt:
      - client_secret_hash
      - client_secret_created_at
      - client_secret_revoked_at
      - enrollment_token_id

    De felter bruges kun internt eller via de dedikerede
    superadmin-endpoints under /client-secret/*.
    """
    id: Optional[int] = None
    machine_id: Optional[str] = None
    status: Optional[str] = "pending"
    deleted_at: Optional[datetime] = None
    deleted_by_user_id: Optional[int] = None
    deleted_reason: Optional[str] = None
    deleted_previous_status: Optional[str] = None
    restored_at: Optional[datetime] = None
    restored_by_user_id: Optional[int] = None
    presence: ClientPresenceRead = Field(default_factory=ClientPresenceRead)
    sort_order: Optional[int] = None
    kiosk_url: Optional[str] = None
    browser_refresh_interval_sec: Optional[int] = Field(default=900)
    ubuntu_version: Optional[str] = None
    uptime: Optional[str] = None
    created_at: Optional[datetime] = None
    chrome_status: Optional[str] = "unknown"
    chrome_last_updated: Optional[datetime] = None
    pending_reboot: Optional[bool] = False
    pending_shutdown: Optional[bool] = False
    chrome_color: Optional[str] = None
    chrome_step: Optional[str] = None
    pending_chrome_action: Optional[ChromeAction] = ChromeAction.NONE
    pending_chrome_action_source: Optional[str] = None
    organization_id: Optional[int] = None
    state: Optional[str] = "normal"
    last_boot_id: Optional[str] = None
    last_boot_at: Optional[datetime] = None
    last_power_event: Optional[str] = None
    last_power_event_at: Optional[datetime] = None
    last_power_event_source: Optional[str] = None
    last_reboot_started_at: Optional[datetime] = None
    last_shutdown_started_at: Optional[datetime] = None
    livestream_status: Optional[str] = "idle"
    livestream_desired_state: Optional[str] = "stopped"
    livestream_stop_reason: Optional[str] = None
    livestream_last_segment: Optional[datetime] = None
    livestream_last_error: Optional[str] = None
    diagnostics_updated_at: Optional[datetime] = None
    system_timezone: Optional[str] = None
    ntp_enabled: Optional[bool] = None
    ntp_synchronized: Optional[bool] = None
    client_time_utc: Optional[datetime] = None
    clock_drift_seconds: Optional[float] = None
    time_sync_status: Optional[str] = "unknown"
    time_sync_message: Optional[str] = None
    active_network_type: Optional[str] = None
    active_network_interface: Optional[str] = None
    active_network_ip: Optional[str] = None
    active_network_mac: Optional[str] = None
    # Afledt runtime-status. Gemmes ikke i DB; sættes af backend ved læsning.
    network_status: Optional[str] = None
    network_status_message: Optional[str] = None
    network_status_color: Optional[str] = None
    network_has_connection: Optional[bool] = None
    service_clientflow_status: Optional[str] = None
    service_calendar_status: Optional[str] = None
    service_browser_guard_status: Optional[str] = None
    service_remote_terminal_status: Optional[str] = None
    service_admin_terminal_status: Optional[str] = None
    service_remote_desktop_status: Optional[str] = None
    service_kiosk_x11_guard_status: Optional[str] = None  # legacy/optional; kept for backward compatibility
    service_livestream_status: Optional[str] = None
    service_selfupdate_status: Optional[str] = None
    service_ubuntu_update_status: Optional[str] = None
    service_local_reboot_reporter_status: Optional[str] = None
    service_local_shutdown_reporter_status: Optional[str] = None
    livestream_process_status: Optional[str] = None
    display_resolution_preset: Optional[str] = "auto"
    display_resolution_mode: Optional[str] = "auto"
    display_resolution_width: Optional[int] = None
    display_resolution_height: Optional[int] = None
    display_resolution_refresh_rate: Optional[float] = None
    display_resolution_rotation: Optional[str] = "normal"
    display_resolution_action: Optional[str] = None
    display_resolution_updated_at: Optional[datetime] = None
    display_resolution_current_output: Optional[str] = None
    display_resolution_current_width: Optional[int] = None
    display_resolution_current_height: Optional[int] = None
    display_resolution_current_refresh_rate: Optional[float] = None
    display_resolution_status: Optional[str] = "unknown"
    display_resolution_error: Optional[str] = None
    display_resolution_last_applied_at: Optional[datetime] = None
    display_detected_outputs: Optional[list[Dict[str, Any]]] = None
    display_detected_updated_at: Optional[datetime] = None
    ubuntu_updates_available: Optional[int] = 0
    pending_os_update: Optional[bool] = False
    ubuntu_update_status: Optional[str] = "ready"
    ubuntu_update_step: Optional[str] = None
    ubuntu_update_message: Optional[str] = None
    ubuntu_update_error: Optional[str] = None
    ubuntu_update_started_at: Optional[datetime] = None
    ubuntu_update_updated_at: Optional[datetime] = None
    ubuntu_update_finished_at: Optional[datetime] = None
    ubuntu_update_progress: Optional[int] = None
    ubuntu_update_package_count: Optional[int] = None
    ubuntu_update_reboot_required: Optional[bool] = None
    desktop_lockdown_enabled: Optional[bool] = False
    desktop_lockdown_status: Optional[str] = "unknown"
    desktop_lockdown_message: Optional[str] = None
    desktop_lockdown_updated_at: Optional[datetime] = None
    desktop_lockdown_last_applied_at: Optional[datetime] = None
    client_version: Optional[str] = None
    client_version_patch: Optional[str] = None
    client_version_updated_at: Optional[datetime] = None
    client_update_status: Optional[str] = "ready"
    client_update_message: Optional[str] = None
    client_update_requested_at: Optional[datetime] = None
    client_update_started_at: Optional[datetime] = None
    client_update_finished_at: Optional[datetime] = None
    client_update_error: Optional[str] = None
    client_update_target_version: Optional[str] = "latest"
    client_update_target_release_sequence: Optional[int] = None
    client_update_deployment_sequence: int = 0
    client_update_applied_deployment_sequence: int = 0
    client_update_allow_downgrade: bool = False
    client_update_reason: Optional[str] = None
    local_management_action: Optional[str] = None
    local_management_request_id: Optional[str] = None
    local_management_desired_hostname: Optional[str] = None
    local_management_status: Optional[str] = "ready"
    local_management_message: Optional[str] = None
    local_management_requested_at: Optional[datetime] = None
    local_management_started_at: Optional[datetime] = None
    local_management_finished_at: Optional[datetime] = None
    local_management_error: Optional[str] = None


class ClientCreate(ClientBase):
    machine_id: Optional[str] = None
    sort_order: Optional[int] = None
    kiosk_url: Optional[str] = None
    browser_refresh_interval_sec: Optional[int] = Field(default=900)
    ubuntu_version: Optional[str] = None
    uptime: Optional[str] = None
    wifi_ip_address: Optional[str] = None
    wifi_mac_address: Optional[str] = None
    lan_ip_address: Optional[str] = None
    lan_mac_address: Optional[str] = None
    chrome_status: Optional[str] = None
    chrome_color: Optional[str] = None
    chrome_step: Optional[str] = None
    pending_chrome_action: Optional[ChromeAction] = ChromeAction.NONE
    pending_chrome_action_source: Optional[str] = None
    organization_id: Optional[int] = None
    state: Optional[str] = Field(default="normal")
    last_boot_id: Optional[str] = None
    last_boot_at: Optional[datetime] = None
    last_power_event: Optional[str] = None
    last_power_event_at: Optional[datetime] = None
    last_power_event_source: Optional[str] = None
    last_reboot_started_at: Optional[datetime] = None
    last_shutdown_started_at: Optional[datetime] = None
    ubuntu_updates_available: Optional[int] = 0
    pending_os_update: Optional[bool] = False
    ubuntu_update_status: Optional[str] = "ready"
    ubuntu_update_step: Optional[str] = None
    ubuntu_update_message: Optional[str] = None
    ubuntu_update_error: Optional[str] = None
    ubuntu_update_started_at: Optional[datetime] = None
    ubuntu_update_updated_at: Optional[datetime] = None
    ubuntu_update_finished_at: Optional[datetime] = None
    ubuntu_update_progress: Optional[int] = None
    ubuntu_update_package_count: Optional[int] = None
    ubuntu_update_reboot_required: Optional[bool] = None
    desktop_lockdown_enabled: Optional[bool] = False
    desktop_lockdown_status: Optional[str] = "unknown"
    desktop_lockdown_message: Optional[str] = None
    desktop_lockdown_updated_at: Optional[datetime] = None
    desktop_lockdown_last_applied_at: Optional[datetime] = None
    client_version: Optional[str] = None
    client_version_patch: Optional[str] = None
    client_version_updated_at: Optional[datetime] = None
    client_update_status: Optional[str] = "ready"
    client_update_message: Optional[str] = None
    client_update_requested_at: Optional[datetime] = None
    client_update_started_at: Optional[datetime] = None
    client_update_finished_at: Optional[datetime] = None
    client_update_error: Optional[str] = None
    client_update_target_version: Optional[str] = "latest"
    client_update_target_release_sequence: Optional[int] = None
    client_update_deployment_sequence: int = 0
    client_update_applied_deployment_sequence: int = 0
    client_update_allow_downgrade: bool = False
    client_update_reason: Optional[str] = None
    diagnostics_updated_at: Optional[datetime] = None
    system_timezone: Optional[str] = None
    ntp_enabled: Optional[bool] = None
    ntp_synchronized: Optional[bool] = None
    client_time_utc: Optional[datetime] = None
    active_network_type: Optional[str] = None
    active_network_interface: Optional[str] = None
    active_network_ip: Optional[str] = None
    active_network_mac: Optional[str] = None
    service_clientflow_status: Optional[str] = None
    service_calendar_status: Optional[str] = None
    service_browser_guard_status: Optional[str] = None
    service_remote_terminal_status: Optional[str] = None
    service_admin_terminal_status: Optional[str] = None
    service_remote_desktop_status: Optional[str] = None
    service_kiosk_x11_guard_status: Optional[str] = None  # legacy/optional; kept for backward compatibility
    service_livestream_status: Optional[str] = None
    service_selfupdate_status: Optional[str] = None
    service_ubuntu_update_status: Optional[str] = None
    service_local_reboot_reporter_status: Optional[str] = None
    service_local_shutdown_reporter_status: Optional[str] = None
    livestream_process_status: Optional[str] = None
    display_resolution_preset: Optional[str] = "auto"
    display_resolution_mode: Optional[str] = "auto"
    display_resolution_width: Optional[int] = None
    display_resolution_height: Optional[int] = None
    display_resolution_refresh_rate: Optional[float] = None
    display_resolution_rotation: Optional[str] = "normal"
    display_resolution_action: Optional[str] = None
    display_resolution_updated_at: Optional[datetime] = None
    display_resolution_current_output: Optional[str] = None
    display_resolution_current_width: Optional[int] = None
    display_resolution_current_height: Optional[int] = None
    display_resolution_current_refresh_rate: Optional[float] = None
    display_resolution_status: Optional[str] = "unknown"
    display_resolution_error: Optional[str] = None
    display_resolution_last_applied_at: Optional[datetime] = None
    display_detected_outputs: Optional[list[Dict[str, Any]]] = None
    display_detected_updated_at: Optional[datetime] = None



class ClientUpdate(SQLModel):
    name: Optional[str] = None
    machine_id: Optional[str] = None
    locality: Optional[str] = None
    sort_order: Optional[int] = None
    kiosk_url: Optional[str] = None
    browser_refresh_interval_sec: Optional[int] = Field(default=900)
    ubuntu_version: Optional[str] = None
    uptime: Optional[str] = None
    wifi_ip_address: Optional[str] = None
    wifi_mac_address: Optional[str] = None
    lan_ip_address: Optional[str] = None
    lan_mac_address: Optional[str] = None
    pending_reboot: Optional[bool] = None
    pending_shutdown: Optional[bool] = None
    chrome_status: Optional[str] = None
    chrome_last_updated: Optional[datetime] = None
    chrome_color: Optional[str] = None
    # FIX: chrome_step kan nu opdateres via /update endpoint
    chrome_step: Optional[str] = None
    created_at: Optional[datetime] = None
    pending_chrome_action: Optional[ChromeAction] = None
    pending_chrome_action_source: Optional[str] = None
    organization_id: Optional[int] = None
    state: Optional[str] = None
    last_boot_id: Optional[str] = None
    last_boot_at: Optional[datetime] = None
    last_power_event: Optional[str] = None
    last_power_event_at: Optional[datetime] = None
    last_power_event_source: Optional[str] = None
    last_reboot_started_at: Optional[datetime] = None
    last_shutdown_started_at: Optional[datetime] = None
    livestream_status: Optional[str] = None
    livestream_last_segment: Optional[datetime] = None
    livestream_last_error: Optional[str] = None
    diagnostics_updated_at: Optional[datetime] = None
    system_timezone: Optional[str] = None
    ntp_enabled: Optional[bool] = None
    ntp_synchronized: Optional[bool] = None
    client_time_utc: Optional[datetime] = None
    active_network_type: Optional[str] = None
    active_network_interface: Optional[str] = None
    active_network_ip: Optional[str] = None
    active_network_mac: Optional[str] = None
    service_clientflow_status: Optional[str] = None
    service_calendar_status: Optional[str] = None
    service_browser_guard_status: Optional[str] = None
    service_remote_terminal_status: Optional[str] = None
    service_admin_terminal_status: Optional[str] = None
    service_remote_desktop_status: Optional[str] = None
    service_kiosk_x11_guard_status: Optional[str] = None  # legacy/optional; kept for backward compatibility
    service_livestream_status: Optional[str] = None
    service_selfupdate_status: Optional[str] = None
    service_ubuntu_update_status: Optional[str] = None
    service_local_reboot_reporter_status: Optional[str] = None
    service_local_shutdown_reporter_status: Optional[str] = None
    livestream_process_status: Optional[str] = None
    display_resolution_preset: Optional[str] = None
    display_resolution_mode: Optional[str] = None
    display_resolution_width: Optional[int] = None
    display_resolution_height: Optional[int] = None
    display_resolution_refresh_rate: Optional[float] = None
    display_resolution_rotation: Optional[str] = None
    display_resolution_action: Optional[str] = None
    display_resolution_updated_at: Optional[datetime] = None
    display_resolution_current_output: Optional[str] = None
    display_resolution_current_width: Optional[int] = None
    display_resolution_current_height: Optional[int] = None
    display_resolution_current_refresh_rate: Optional[float] = None
    display_resolution_status: Optional[str] = None
    display_resolution_error: Optional[str] = None
    display_resolution_last_applied_at: Optional[datetime] = None
    display_detected_outputs: Optional[list[Dict[str, Any]]] = None
    display_detected_updated_at: Optional[datetime] = None
    ubuntu_updates_available: Optional[int] = None
    pending_os_update: Optional[bool] = None
    ubuntu_update_status: Optional[str] = None
    ubuntu_update_step: Optional[str] = None
    ubuntu_update_message: Optional[str] = None
    ubuntu_update_error: Optional[str] = None
    ubuntu_update_started_at: Optional[datetime] = None
    ubuntu_update_updated_at: Optional[datetime] = None
    ubuntu_update_finished_at: Optional[datetime] = None
    ubuntu_update_progress: Optional[int] = None
    ubuntu_update_package_count: Optional[int] = None
    ubuntu_update_reboot_required: Optional[bool] = None
    desktop_lockdown_enabled: Optional[bool] = None
    desktop_lockdown_status: Optional[str] = None
    desktop_lockdown_message: Optional[str] = None
    desktop_lockdown_updated_at: Optional[datetime] = None
    desktop_lockdown_last_applied_at: Optional[datetime] = None
    client_version: Optional[str] = None
    client_version_patch: Optional[str] = None
    client_version_updated_at: Optional[datetime] = None
    client_update_status: Optional[str] = None
    client_update_message: Optional[str] = None
    client_update_requested_at: Optional[datetime] = None
    client_update_started_at: Optional[datetime] = None
    client_update_finished_at: Optional[datetime] = None
    client_update_error: Optional[str] = None
    client_update_target_version: Optional[str] = "latest"
    client_update_target_release_sequence: Optional[int] = None
    client_update_deployment_sequence: int = 0
    client_update_applied_deployment_sequence: int = 0
    client_update_allow_downgrade: bool = False
    client_update_reason: Optional[str] = None



class LivestreamViewerLease(SQLModel, table=True):
    __tablename__ = "livestream_viewer_lease"
    __table_args__ = (
        UniqueConstraint("client_id", "viewer_id", name="uq_livestream_viewer_lease_client_viewer"),
        Index("ix_livestream_viewer_lease_expires_at", "expires_at"),
        Index("ix_livestream_viewer_lease_client_id", "client_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", nullable=False)
    viewer_id: str = Field(max_length=120, nullable=False)
    source: Optional[str] = Field(default=None, max_length=120)
    last_seen_at: datetime = Field(default_factory=utcnow, nullable=False)
    expires_at: datetime = Field(nullable=False)

class EnrollmentToken(SQLModel, table=True):
    """
    Engangs installationskode til nye Ubuntu-klienter.

    Selve koden gemmes aldrig i klartekst. Kun hash gemmes.
    Koden vises kun én gang ved oprettelse i admin-UI.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    code_hash: str
    code_preview: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    expires_at: datetime
    used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    used_by_client_id: Optional[int] = Field(default=None, foreign_key="client.id")
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id")


    note: Optional[str] = None

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class CalendarMarking(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("client_id", "season", name="calendarmarking_client_season_unique"),
        Index("idx_calendarmarking_client_id", "client_id"),
        Index("idx_calendarmarking_season", "season"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    season: str = Field(sa_column=Column(Text, nullable=False))
    client_id: int = Field(foreign_key="client.id")
    markings: Dict[str, Any] = Field(sa_column=Column(_jsonb_type(), nullable=True))



# ---------------------------------------------------------------------------
# Organization API schemas
# ---------------------------------------------------------------------------
#
# Organisationstider er nu ugedagsspecifikke og gemmes kun som day_times.

class OrganizationBase(SQLModel):
    name: str
    day_times: Dict[str, Dict[str, str]] = Field(default_factory=default_day_times)


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationRead(OrganizationBase):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    organization_id: Optional[int] = None
    has_logo: bool = False
    logo_content_type: Optional[str] = None
    logo_updated_at: Optional[datetime] = None
    logo_url: Optional[str] = None


class OrganizationTimesUpdate(SQLModel):
    day_times: Dict[str, Dict[str, str]]


class OrganizationSeasonTimesReplace(OrganizationTimesUpdate):
    confirmation: str


class OrganizationNameUpdate(SQLModel):
    name: str


class OrganizationTimesRead(SQLModel):
    organization_id: int
    season: Optional[str] = None
    day_times: Dict[str, Dict[str, str]]
