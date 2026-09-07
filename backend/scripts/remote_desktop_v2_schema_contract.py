"""Reviewed production catalog contract for Remote Desktop-owned v2 storage."""

REMOTE_DESKTOP_V2_TABLES = {
    "remote_desktop_client",
    "remote_desktop_credential",
    "remote_desktop_agent_status",
}

REMOTE_DESKTOP_V2_COLUMNS = {
    "remote_desktop_client": {
        "id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "display_name": {"data_type": "character varying", "default": None, "length": 255, "nullable": True, "udt_name": "varchar"},
        "status": {"data_type": "character varying", "default": "'approved'::character varying", "length": 32, "nullable": False, "udt_name": "varchar"},
        "created_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
    },
    "remote_desktop_credential": {
        "id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "secret_hash": {"data_type": "text", "default": None, "length": None, "nullable": False, "udt_name": "text"},
        "token_version": {"data_type": "integer", "default": "0", "length": None, "nullable": False, "udt_name": "int4"},
        "created_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "last_used_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
        "revoked_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
    },
    "remote_desktop_agent_status": {
        "id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "schema_version": {"data_type": "integer", "default": "1", "length": None, "nullable": False, "udt_name": "int4"},
        "observed_state": {"data_type": "character varying", "default": "'unknown'::character varying", "length": 80, "nullable": False, "udt_name": "varchar"},
        "status_payload": {"data_type": "jsonb", "default": None, "length": None, "nullable": False, "udt_name": "jsonb"},
        "agent_version": {"data_type": "character varying", "default": None, "length": 80, "nullable": True, "udt_name": "varchar"},
        "boot_id": {"data_type": "character varying", "default": None, "length": 128, "nullable": True, "udt_name": "varchar"},
        "credential_id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "reported_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
    },
}

REMOTE_DESKTOP_V2_CONSTRAINTS = {
    "ck_remote_desktop_client_status": "CHECK (status::text = ANY (ARRAY['approved'::character varying::text, 'disabled'::character varying::text]))",
    "remote_desktop_client_pkey": "PRIMARY KEY (id)",
    "ck_remote_desktop_credential_token_version": "CHECK (token_version >= 0)",
    "remote_desktop_credential_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES remote_desktop_client(id)",
    "remote_desktop_credential_pkey": "PRIMARY KEY (id)",
    "uq_remote_desktop_credential_client": "UNIQUE (client_id)",
    "ck_remote_desktop_agent_status_schema_version": "CHECK (schema_version >= 1)",
    "remote_desktop_agent_status_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES remote_desktop_client(id)",
    "remote_desktop_agent_status_credential_id_fkey": "FOREIGN KEY (credential_id) REFERENCES remote_desktop_credential(id)",
    "remote_desktop_agent_status_pkey": "PRIMARY KEY (id)",
    "uq_remote_desktop_agent_status_client": "UNIQUE (client_id)",
}

REMOTE_DESKTOP_V2_INDEXES = {
    "remote_desktop_client_pkey": "CREATE UNIQUE INDEX remote_desktop_client_pkey ON public.remote_desktop_client USING btree (id)",
    "ix_remote_desktop_client_status": "CREATE INDEX ix_remote_desktop_client_status ON public.remote_desktop_client USING btree (status)",
    "remote_desktop_credential_pkey": "CREATE UNIQUE INDEX remote_desktop_credential_pkey ON public.remote_desktop_credential USING btree (id)",
    "ix_remote_desktop_credential_active": "CREATE INDEX ix_remote_desktop_credential_active ON public.remote_desktop_credential USING btree (client_id, revoked_at)",
    "ix_remote_desktop_credential_last_used_at": "CREATE INDEX ix_remote_desktop_credential_last_used_at ON public.remote_desktop_credential USING btree (last_used_at)",
    "ix_remote_desktop_credential_revoked_at": "CREATE INDEX ix_remote_desktop_credential_revoked_at ON public.remote_desktop_credential USING btree (revoked_at)",
    "uq_remote_desktop_credential_client": "CREATE UNIQUE INDEX uq_remote_desktop_credential_client ON public.remote_desktop_credential USING btree (client_id)",
    "remote_desktop_agent_status_pkey": "CREATE UNIQUE INDEX remote_desktop_agent_status_pkey ON public.remote_desktop_agent_status USING btree (id)",
    "ix_remote_desktop_agent_status_reported_at": "CREATE INDEX ix_remote_desktop_agent_status_reported_at ON public.remote_desktop_agent_status USING btree (reported_at)",
    "uq_remote_desktop_agent_status_client": "CREATE UNIQUE INDEX uq_remote_desktop_agent_status_client ON public.remote_desktop_agent_status USING btree (client_id)",
}
