"""Exact Step 51B ClientFlow update-auth replay and reprovision schema contract."""

CLIENTFLOW_UPDATE_AUTH_TABLES = {
    "clientflow_update_replay",
    "clientflow_update_provisioning_token",
}

CLIENTFLOW_UPDATE_AUTH_COLUMNS = {
    "clientflow_update_replay": {
        "id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "credential_id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "kind": {"data_type": "character varying", "default": None, "length": 24, "nullable": False, "udt_name": "varchar"},
        "jti_hash": {"data_type": "character varying", "default": None, "length": 64, "nullable": False, "udt_name": "varchar"},
        "created_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "expires_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
    },
    "clientflow_update_provisioning_token": {
        "id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "code_hash": {"data_type": "character varying", "default": None, "length": 64, "nullable": False, "udt_name": "varchar"},
        "purpose": {"data_type": "character varying", "default": None, "length": 20, "nullable": False, "udt_name": "varchar"},
        "created_by_user_id": {"data_type": "integer", "default": None, "length": None, "nullable": True, "udt_name": "int4"},
        "created_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "expires_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "used_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
        "revoked_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
    },
}

CLIENTFLOW_UPDATE_AUTH_CONSTRAINTS = {
    "clientflow_update_replay_pkey": "PRIMARY KEY (id)",
    "clientflow_update_replay_credential_id_fkey": "FOREIGN KEY (credential_id) REFERENCES clientflow_update_credential(id) ON DELETE CASCADE",
    "uq_clientflow_update_replay_jti_hash": "UNIQUE (jti_hash)",
    "ck_clientflow_update_replay_kind": "CHECK (kind::text = ANY (ARRAY['client_assertion'::character varying::text, 'dpop'::character varying::text]))",
    "clientflow_update_provisioning_token_pkey": "PRIMARY KEY (id)",
    "clientflow_update_provisioning_token_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES client(id)",
    "clientflow_update_provisioning_token_created_by_user_id_fkey": 'FOREIGN KEY (created_by_user_id) REFERENCES "user"(id) ON DELETE SET NULL',
    "ck_clientflow_update_provisioning_token_purpose": "CHECK (purpose::text = ANY (ARRAY['bootstrap'::character varying::text, 'recovery'::character varying::text]))",
    "ck_clientflow_update_provisioning_token_expiry": "CHECK (expires_at > created_at)",
}

CLIENTFLOW_UPDATE_AUTH_INDEXES = {
    "clientflow_update_replay_pkey": "CREATE UNIQUE INDEX clientflow_update_replay_pkey ON public.clientflow_update_replay USING btree (id)",
    "uq_clientflow_update_replay_jti_hash": "CREATE UNIQUE INDEX uq_clientflow_update_replay_jti_hash ON public.clientflow_update_replay USING btree (jti_hash)",
    "ix_clientflow_update_replay_expires_at": "CREATE INDEX ix_clientflow_update_replay_expires_at ON public.clientflow_update_replay USING btree (expires_at)",
    "ix_clientflow_update_replay_credential_id": "CREATE INDEX ix_clientflow_update_replay_credential_id ON public.clientflow_update_replay USING btree (credential_id)",
    "clientflow_update_provisioning_token_pkey": "CREATE UNIQUE INDEX clientflow_update_provisioning_token_pkey ON public.clientflow_update_provisioning_token USING btree (id)",
    "ix_clientflow_update_provisioning_token_client_id": "CREATE INDEX ix_clientflow_update_provisioning_token_client_id ON public.clientflow_update_provisioning_token USING btree (client_id)",
    "ix_clientflow_update_provisioning_token_expires_at": "CREATE INDEX ix_clientflow_update_provisioning_token_expires_at ON public.clientflow_update_provisioning_token USING btree (expires_at)",
    "uq_clientflow_update_provisioning_token_code_hash": "CREATE UNIQUE INDEX uq_clientflow_update_provisioning_token_code_hash ON public.clientflow_update_provisioning_token USING btree (code_hash)",
    "uq_clientflow_update_provisioning_token_active_client": "CREATE UNIQUE INDEX uq_clientflow_update_provisioning_token_active_client ON public.clientflow_update_provisioning_token USING btree (client_id) WHERE ((used_at IS NULL) AND (revoked_at IS NULL))",
}
