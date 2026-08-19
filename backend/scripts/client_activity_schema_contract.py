"""Reviewed production catalog contract for shared client activity leases."""

CLIENT_ACTIVITY_TABLES = {"client_activity_lease"}

CLIENT_ACTIVITY_COLUMNS = {
    "client_activity_lease": {
        "id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "domain": {"data_type": "character varying", "default": None, "length": 32, "nullable": False, "udt_name": "varchar"},
        "session_id": {"data_type": "character varying", "default": None, "length": 64, "nullable": False, "udt_name": "varchar"},
        "created_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "last_seen_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "ended_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
        "end_reason": {"data_type": "character varying", "default": None, "length": 32, "nullable": True, "udt_name": "varchar"},
    },
}

CLIENT_ACTIVITY_CONSTRAINTS = {
    "ck_client_activity_lease_domain": "CHECK (domain::text = ANY (ARRAY['terminal'::character varying, 'remote_desktop'::character varying]::text[]))",
    "client_activity_lease_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES client(id)",
    "client_activity_lease_pkey": "PRIMARY KEY (id)",
    "uq_client_activity_lease_client_domain_session": "UNIQUE (client_id, domain, session_id)",
}

CLIENT_ACTIVITY_INDEXES = {
    "client_activity_lease_pkey": "CREATE UNIQUE INDEX client_activity_lease_pkey ON public.client_activity_lease USING btree (id)",
    "uq_client_activity_lease_client_domain_session": "CREATE UNIQUE INDEX uq_client_activity_lease_client_domain_session ON public.client_activity_lease USING btree (client_id, domain, session_id)",
    "ix_client_activity_lease_client_id": "CREATE INDEX ix_client_activity_lease_client_id ON public.client_activity_lease USING btree (client_id)",
    "ix_client_activity_lease_last_seen_at": "CREATE INDEX ix_client_activity_lease_last_seen_at ON public.client_activity_lease USING btree (last_seen_at)",
    "ix_client_activity_lease_ended_at": "CREATE INDEX ix_client_activity_lease_ended_at ON public.client_activity_lease USING btree (ended_at)",
    "ix_client_activity_lease_active": "CREATE INDEX ix_client_activity_lease_active ON public.client_activity_lease USING btree (client_id, domain, ended_at, last_seen_at)",
}
