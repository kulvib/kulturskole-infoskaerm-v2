"""Frozen PlanIQ Display production baseline.

This revision is a literal snapshot of the verified Display production schema
on 2026-07-12. It must not import runtime models or call metadata.create_all().
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260712_30d_display_base'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SEQUENCE audit_logs_id_seq AS INTEGER START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))
    op.execute(sa.text("CREATE SEQUENCE calendarmarking_id_seq AS INTEGER START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))
    op.execute(sa.text("CREATE SEQUENCE client_id_seq AS INTEGER START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))
    op.execute(sa.text("CREATE SEQUENCE enrollmenttoken_id_seq AS INTEGER START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))
    op.execute(sa.text("CREATE SEQUENCE refresh_tokens_id_seq AS INTEGER START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))
    op.execute(sa.text("CREATE SEQUENCE school_id_seq AS INTEGER START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))
    op.execute(sa.text("CREATE SEQUENCE schoolseasontimes_id_seq AS INTEGER START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))
    op.execute(sa.text("CREATE SEQUENCE user_id_seq AS INTEGER START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1"))

    op.create_table('organization',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('school_id_seq'::regclass)"), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('day_times', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("jsonb_build_object('monday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'tuesday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'wednesday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'thursday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'friday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'saturday', jsonb_build_object('onTime', '08:00', 'offTime', '18:00'), 'sunday', jsonb_build_object('onTime', '08:00', 'offTime', '18:00'))"), nullable=False),
        sa.PrimaryKeyConstraint('id', name='school_pkey'),
    )

    op.create_table('user',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('user_id_seq'::regclass)"), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('role', sa.String(), server_default=sa.text("'admin'::character varying"), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('email', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('must_change_password', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), server_default=sa.text('now()'), nullable=False),
        sa.Column('token_version', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('password_reset_token_hash', sa.String(), nullable=True),
        sa.Column('password_reset_expires_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('last_login_ip', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='user_pkey'),
    )

    op.create_table('refresh_tokens',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('refresh_tokens_id_seq'::regclass)"), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=False), nullable=False),
        sa.Column('session_expires_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('created_ip', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint('id', name='refresh_tokens_pkey'),
    )

    op.create_table('audit_logs',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('audit_logs_id_seq'::regclass)"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('actor_username', sa.String(), nullable=True),
        sa.Column('actor_role', sa.String(), nullable=True),
        sa.Column('actor_organization_id', sa.Integer(), nullable=True),
        sa.Column('target_user_id', sa.Integer(), nullable=True),
        sa.Column('target_username', sa.String(), nullable=True),
        sa.Column('target_organization_id', sa.Integer(), nullable=True),
        sa.Column('entity_type', sa.String(), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('entity_label', sa.String(), nullable=True),
        sa.Column('request_ip', sa.String(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('is_critical', sa.Boolean(), nullable=False),
        sa.Column('retention_days', sa.Integer(), nullable=True),
        sa.Column('retain_until', sa.DateTime(timezone=False), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='audit_logs_pkey'),
    )

    op.create_table('organizationseasontimes',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('schoolseasontimes_id_seq'::regclass)"), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('season', sa.Text(), nullable=False),
        sa.Column('day_times', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("jsonb_build_object('monday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'tuesday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'wednesday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'thursday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'friday', jsonb_build_object('onTime', '09:00', 'offTime', '22:30'), 'saturday', jsonb_build_object('onTime', '08:00', 'offTime', '18:00'), 'sunday', jsonb_build_object('onTime', '08:00', 'offTime', '18:00'))"), nullable=False),
        sa.PrimaryKeyConstraint('id', name='schoolseasontimes_pkey'),
    )

    op.create_table('organizationlogo',
        sa.Column('organization_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=False), server_default=sa.text('now()'), nullable=False),
        sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('organization_id', name='organizationlogo_pkey'),
    )

    op.create_table('client',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('client_id_seq'::regclass)"), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('locality', sa.String(), nullable=True),
        sa.Column('wifi_ip_address', sa.String(), nullable=True),
        sa.Column('wifi_mac_address', sa.String(), nullable=True),
        sa.Column('lan_ip_address', sa.String(), nullable=True),
        sa.Column('lan_mac_address', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default=sa.text("'pending'::character varying"), nullable=True),
        sa.Column('isOnline', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=False), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.Column('kiosk_url', sa.String(), nullable=True),
        sa.Column('ubuntu_version', sa.String(), nullable=True),
        sa.Column('uptime', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('chrome_status', sa.Text(), nullable=True),
        sa.Column('chrome_last_updated', sa.DateTime(timezone=False), nullable=True),
        sa.Column('pending_reboot', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('pending_shutdown', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('chrome_color', sa.Text(), nullable=True),
        sa.Column('pending_chrome_action', sa.String(length=20), nullable=True),
        sa.Column('school', sa.String(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('state', sa.String(length=32), server_default=sa.text("'normal'::character varying"), nullable=True),
        sa.Column('livestream_status', sa.String(length=50), nullable=True),
        sa.Column('livestream_last_segment', sa.DateTime(timezone=False), nullable=True),
        sa.Column('livestream_last_error', sa.Text(), nullable=True),
        sa.Column('pending_chrome_action_source', sa.Text(), nullable=True),
        sa.Column('ubuntu_updates_available', sa.Integer(), server_default=sa.text('0'), nullable=True),
        sa.Column('pending_os_update', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('chrome_step', sa.String(), nullable=True),
        sa.Column('client_secret_hash', sa.Text(), nullable=True),
        sa.Column('client_secret_created_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('client_secret_revoked_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('enrollment_token_id', sa.Integer(), nullable=True),
        sa.Column('machine_id', sa.Text(), nullable=True),
        sa.Column('client_version', sa.Text(), nullable=True),
        sa.Column('client_update_status', sa.Text(), server_default=sa.text("'ready'::text"), nullable=True),
        sa.Column('client_update_message', sa.Text(), nullable=True),
        sa.Column('client_update_requested_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('client_update_started_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('client_update_finished_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('client_update_error', sa.Text(), nullable=True),
        sa.Column('display_resolution_preset', sa.Text(), server_default=sa.text("'auto'::text"), nullable=True),
        sa.Column('display_resolution_mode', sa.Text(), server_default=sa.text("'auto'::text"), nullable=True),
        sa.Column('display_resolution_width', sa.Integer(), nullable=True),
        sa.Column('display_resolution_height', sa.Integer(), nullable=True),
        sa.Column('display_resolution_refresh_rate', sa.Float(precision=53), nullable=True),
        sa.Column('display_resolution_rotation', sa.Text(), server_default=sa.text("'normal'::text"), nullable=True),
        sa.Column('display_resolution_updated_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('display_resolution_current_output', sa.Text(), nullable=True),
        sa.Column('display_resolution_current_width', sa.Integer(), nullable=True),
        sa.Column('display_resolution_current_height', sa.Integer(), nullable=True),
        sa.Column('display_resolution_current_refresh_rate', sa.Float(precision=53), nullable=True),
        sa.Column('display_resolution_status', sa.Text(), server_default=sa.text("'unknown'::text"), nullable=True),
        sa.Column('display_resolution_error', sa.Text(), nullable=True),
        sa.Column('display_resolution_last_applied_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('display_resolution_action', sa.Text(), nullable=True),
        sa.Column('diagnostics_updated_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('active_network_type', sa.Text(), nullable=True),
        sa.Column('active_network_interface', sa.Text(), nullable=True),
        sa.Column('active_network_ip', sa.Text(), nullable=True),
        sa.Column('active_network_mac', sa.Text(), nullable=True),
        sa.Column('service_clientflow_status', sa.Text(), nullable=True),
        sa.Column('service_calendar_status', sa.Text(), nullable=True),
        sa.Column('service_browser_guard_status', sa.Text(), nullable=True),
        sa.Column('service_remote_terminal_status', sa.Text(), nullable=True),
        sa.Column('service_admin_terminal_status', sa.Text(), nullable=True),
        sa.Column('service_remote_desktop_status', sa.Text(), nullable=True),
        sa.Column('service_kiosk_x11_guard_status', sa.Text(), nullable=True),
        sa.Column('service_selfupdate_status', sa.Text(), nullable=True),
        sa.Column('livestream_process_status', sa.Text(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('deleted_by_user_id', sa.Integer(), nullable=True),
        sa.Column('deleted_reason', sa.Text(), nullable=True),
        sa.Column('deleted_previous_status', sa.Text(), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('restored_by_user_id', sa.Integer(), nullable=True),
        sa.Column('client_token_version', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('browser_refresh_interval_sec', sa.Integer(), server_default=sa.text('900'), nullable=True),
        sa.Column('desktop_lockdown_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('desktop_lockdown_status', sa.Text(), server_default=sa.text("'unknown'::text"), nullable=True),
        sa.Column('desktop_lockdown_message', sa.Text(), nullable=True),
        sa.Column('desktop_lockdown_updated_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('desktop_lockdown_last_applied_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('display_detected_outputs', sa.JSON(), nullable=True),
        sa.Column('display_detected_updated_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('livestream_viewer_last_seen', sa.DateTime(timezone=False), nullable=True),
        sa.Column('livestream_viewer_count', sa.Integer(), server_default=sa.text('0'), nullable=True),
        sa.Column('livestream_desired_state', sa.String(), server_default=sa.text("'stopped'::character varying"), nullable=True),
        sa.Column('last_boot_id', sa.String(), nullable=True),
        sa.Column('last_boot_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('last_power_event', sa.String(), nullable=True),
        sa.Column('last_power_event_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('last_power_event_source', sa.String(), nullable=True),
        sa.Column('last_reboot_started_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('last_shutdown_started_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('service_livestream_status', sa.Text(), nullable=True),
        sa.Column('service_ubuntu_update_status', sa.Text(), nullable=True),
        sa.Column('service_local_reboot_reporter_status', sa.Text(), nullable=True),
        sa.Column('service_local_shutdown_reporter_status', sa.Text(), nullable=True),
        sa.Column('local_management_action', sa.Text(), nullable=True),
        sa.Column('local_management_request_id', sa.Text(), nullable=True),
        sa.Column('local_management_desired_hostname', sa.Text(), nullable=True),
        sa.Column('local_management_secret', sa.Text(), nullable=True),
        sa.Column('local_management_status', sa.Text(), server_default=sa.text("'ready'::text"), nullable=True),
        sa.Column('local_management_message', sa.Text(), nullable=True),
        sa.Column('local_management_requested_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('local_management_started_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('local_management_finished_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('local_management_error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='client_pkey'),
    )

    op.create_table('enrollmenttoken',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('enrollmenttoken_id_seq'::regclass)"), nullable=False),
        sa.Column('code_hash', sa.String(), nullable=False),
        sa.Column('code_preview', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=False), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=False), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('used_by_client_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='enrollmenttoken_pkey'),
    )

    op.create_table('calendarmarking',
        sa.Column('id', sa.Integer(), server_default=sa.text("nextval('calendarmarking_id_seq'::regclass)"), nullable=False),
        sa.Column('season', sa.Text(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('markings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id', name='calendarmarking_pkey'),
    )

    op.execute(sa.text("ALTER SEQUENCE school_id_seq OWNED BY organization.id"))
    op.execute(sa.text("ALTER SEQUENCE user_id_seq OWNED BY \"user\".id"))
    op.execute(sa.text("ALTER SEQUENCE refresh_tokens_id_seq OWNED BY refresh_tokens.id"))
    op.execute(sa.text("ALTER SEQUENCE audit_logs_id_seq OWNED BY audit_logs.id"))
    op.execute(sa.text("ALTER SEQUENCE schoolseasontimes_id_seq OWNED BY organizationseasontimes.id"))
    op.execute(sa.text("ALTER SEQUENCE client_id_seq OWNED BY client.id"))
    op.execute(sa.text("ALTER SEQUENCE enrollmenttoken_id_seq OWNED BY enrollmenttoken.id"))
    op.execute(sa.text("ALTER SEQUENCE calendarmarking_id_seq OWNED BY calendarmarking.id"))

    op.create_foreign_key('calendarmarking_client_id_fkey', 'calendarmarking', 'client', ['client_id'], ['id'])
    op.create_foreign_key('client_school_id_fkey', 'client', 'organization', ['organization_id'], ['id'])
    op.create_foreign_key('enrollmenttoken_created_by_user_id_fkey', 'enrollmenttoken', 'user', ['created_by_user_id'], ['id'])
    op.create_foreign_key('enrollmenttoken_school_id_fkey', 'enrollmenttoken', 'organization', ['organization_id'], ['id'])
    op.create_foreign_key('enrollmenttoken_used_by_client_id_fkey', 'enrollmenttoken', 'client', ['used_by_client_id'], ['id'])
    op.create_foreign_key('organizationlogo_organization_id_fkey', 'organizationlogo', 'organization', ['organization_id'], ['id'])
    op.create_foreign_key('organizationlogo_uploaded_by_user_id_fkey', 'organizationlogo', 'user', ['uploaded_by_user_id'], ['id'])
    op.create_unique_constraint('organizationseasontimes_org_season_unique', 'organizationseasontimes', ['organization_id', 'season'])
    op.create_foreign_key('schoolseasontimes_school_id_fkey', 'organizationseasontimes', 'organization', ['organization_id'], ['id'])
    op.create_foreign_key('refresh_tokens_user_id_fkey', 'refresh_tokens', 'user', ['user_id'], ['id'])
    op.create_foreign_key('user_school_id_fkey', 'user', 'organization', ['organization_id'], ['id'])
    op.create_check_constraint('users_role_check', 'user', "role::text = ANY (ARRAY['superadmin'::character varying, 'admin'::character varying, 'bruger'::character varying, 'viewer'::character varying]::text[])")

    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False)
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_audit_logs_entity_id', 'audit_logs', ['entity_id'], unique=False)
    op.create_index('ix_audit_logs_entity_type', 'audit_logs', ['entity_type'], unique=False)
    op.create_index('ix_audit_logs_is_critical', 'audit_logs', ['is_critical'], unique=False)
    op.create_index('ix_audit_logs_retain_until', 'audit_logs', ['retain_until'], unique=False)
    op.create_index('ix_audit_logs_severity', 'audit_logs', ['severity'], unique=False)
    op.create_index('ix_audit_logs_target_user_id', 'audit_logs', ['target_user_id'], unique=False)
    op.create_index('idx_calendarmarking_client_id', 'calendarmarking', ['client_id'], unique=False)
    op.create_index('idx_calendarmarking_season', 'calendarmarking', ['season'], unique=False)
    op.create_index('idx_client_deleted_at', 'client', ['deleted_at'], unique=False)
    op.create_index('idx_client_org_deleted_at', 'client', ['organization_id', 'deleted_at'], unique=False)
    op.create_index('idx_client_sort_order', 'client', ['sort_order'], unique=False)
    op.create_index('idx_client_status_deleted_at', 'client', ['status', 'deleted_at'], unique=False)
    op.create_index('ix_client_last_boot_id', 'client', ['last_boot_id'], unique=False)
    op.create_index('ix_client_last_power_event_at', 'client', ['last_power_event_at'], unique=False)
    op.create_index('ix_enrollmenttoken_code_preview', 'enrollmenttoken', ['code_preview'], unique=False)
    op.create_index('ix_school_name', 'organization', ['name'], unique=True)
    op.create_index('ix_organizationlogo_content_type', 'organizationlogo', ['content_type'], unique=False)
    op.create_index('ix_schoolseasontimes_school_id', 'organizationseasontimes', ['organization_id'], unique=False)
    op.create_index('ix_schoolseasontimes_season', 'organizationseasontimes', ['season'], unique=False)
    op.create_index('ix_refresh_tokens_expires_at', 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index('ix_refresh_tokens_revoked_at', 'refresh_tokens', ['revoked_at'], unique=False)
    op.create_index('ix_refresh_tokens_session_expires_at', 'refresh_tokens', ['session_expires_at'], unique=False)
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'], unique=True)
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)
    op.create_index('ix_user_last_login_at', 'user', ['last_login_at'], unique=False)
    op.create_index('ix_user_password_reset_expires_at', 'user', ['password_reset_expires_at'], unique=False)
    op.create_index('ix_user_password_reset_token_hash', 'user', ['password_reset_token_hash'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_user_password_reset_token_hash', table_name='user')
    op.drop_index('ix_user_password_reset_expires_at', table_name='user')
    op.drop_index('ix_user_last_login_at', table_name='user')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_token_hash', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_session_expires_at', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_revoked_at', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_expires_at', table_name='refresh_tokens')
    op.drop_index('ix_schoolseasontimes_season', table_name='organizationseasontimes')
    op.drop_index('ix_schoolseasontimes_school_id', table_name='organizationseasontimes')
    op.drop_index('ix_organizationlogo_content_type', table_name='organizationlogo')
    op.drop_index('ix_school_name', table_name='organization')
    op.drop_index('ix_enrollmenttoken_code_preview', table_name='enrollmenttoken')
    op.drop_index('ix_client_last_power_event_at', table_name='client')
    op.drop_index('ix_client_last_boot_id', table_name='client')
    op.drop_index('idx_client_status_deleted_at', table_name='client')
    op.drop_index('idx_client_sort_order', table_name='client')
    op.drop_index('idx_client_org_deleted_at', table_name='client')
    op.drop_index('idx_client_deleted_at', table_name='client')
    op.drop_index('idx_calendarmarking_season', table_name='calendarmarking')
    op.drop_index('idx_calendarmarking_client_id', table_name='calendarmarking')
    op.drop_index('ix_audit_logs_target_user_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_severity', table_name='audit_logs')
    op.drop_index('ix_audit_logs_retain_until', table_name='audit_logs')
    op.drop_index('ix_audit_logs_is_critical', table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity_type', table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity', table_name='audit_logs')
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_user_id', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_constraint('users_role_check', 'user', type_='check')
    op.drop_constraint('user_school_id_fkey', 'user', type_='foreignkey')
    op.drop_constraint('refresh_tokens_user_id_fkey', 'refresh_tokens', type_='foreignkey')
    op.drop_constraint('schoolseasontimes_school_id_fkey', 'organizationseasontimes', type_='foreignkey')
    op.drop_constraint('organizationseasontimes_org_season_unique', 'organizationseasontimes', type_='unique')
    op.drop_constraint('organizationlogo_uploaded_by_user_id_fkey', 'organizationlogo', type_='foreignkey')
    op.drop_constraint('organizationlogo_organization_id_fkey', 'organizationlogo', type_='foreignkey')
    op.drop_constraint('enrollmenttoken_used_by_client_id_fkey', 'enrollmenttoken', type_='foreignkey')
    op.drop_constraint('enrollmenttoken_school_id_fkey', 'enrollmenttoken', type_='foreignkey')
    op.drop_constraint('enrollmenttoken_created_by_user_id_fkey', 'enrollmenttoken', type_='foreignkey')
    op.drop_constraint('client_school_id_fkey', 'client', type_='foreignkey')
    op.drop_constraint('calendarmarking_client_id_fkey', 'calendarmarking', type_='foreignkey')
    op.drop_table('calendarmarking')
    op.drop_table('enrollmenttoken')
    op.drop_table('client')
    op.drop_table('organizationlogo')
    op.drop_table('organizationseasontimes')
    op.drop_table('audit_logs')
    op.drop_table('refresh_tokens')
    op.drop_table('user')
    op.drop_table('organization')
    op.execute(sa.text("DROP SEQUENCE IF EXISTS user_id_seq"))
    op.execute(sa.text("DROP SEQUENCE IF EXISTS schoolseasontimes_id_seq"))
    op.execute(sa.text("DROP SEQUENCE IF EXISTS school_id_seq"))
    op.execute(sa.text("DROP SEQUENCE IF EXISTS refresh_tokens_id_seq"))
    op.execute(sa.text("DROP SEQUENCE IF EXISTS enrollmenttoken_id_seq"))
    op.execute(sa.text("DROP SEQUENCE IF EXISTS client_id_seq"))
    op.execute(sa.text("DROP SEQUENCE IF EXISTS calendarmarking_id_seq"))
    op.execute(sa.text("DROP SEQUENCE IF EXISTS audit_logs_id_seq"))
