"""Step 53A canonical Display desired-state schema delta."""

DISPLAY_AUTHORITY_TABLES = {"display_desired_configuration"}

DISPLAY_AUTHORITY_COLUMNS = {
    "display_desired_configuration": {
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "schema_version": {"data_type": "integer", "default": "1", "length": None, "nullable": False, "udt_name": "int4"},
        "revision": {"data_type": "integer", "default": "1", "length": None, "nullable": False, "udt_name": "int4"},
        "kiosk_url": {"data_type": "text", "default": None, "length": None, "nullable": True, "udt_name": "text"},
        "updated_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "updated_by_user_id": {"data_type": "integer", "default": None, "length": None, "nullable": True, "udt_name": "int4"},
    },
}

DISPLAY_AUTHORITY_RETIRED_CLIENT_COLUMNS = {
    "kiosk_url": {"data_type": "character varying", "default": None, "length": None, "nullable": True, "udt_name": "varchar"},
    "browser_refresh_interval_sec": {"data_type": "integer", "default": "900", "length": None, "nullable": True, "udt_name": "int4"},
}

DISPLAY_AUTHORITY_CONSTRAINTS = {
    "ck_display_desired_configuration_revision": "CHECK (revision >= 1)",
    "ck_display_desired_configuration_schema_version": "CHECK (schema_version = 1)",
    "display_desired_configuration_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES client(id) ON DELETE CASCADE",
    "display_desired_configuration_updated_by_user_id_fkey": 'FOREIGN KEY (updated_by_user_id) REFERENCES "user"(id) ON DELETE SET NULL',
    "display_desired_configuration_pkey": "PRIMARY KEY (client_id)",
}

DISPLAY_AUTHORITY_INDEXES = {
    "display_desired_configuration_pkey": "CREATE UNIQUE INDEX display_desired_configuration_pkey ON public.display_desired_configuration USING btree (client_id)",
    "ix_display_desired_configuration_updated_at": "CREATE INDEX ix_display_desired_configuration_updated_at ON public.display_desired_configuration USING btree (updated_at)",
}
