"""Exact Step 50A canonical shared-foundations schema contract."""

CANONICAL_FOUNDATION_TABLES = {
    "client_enrollment_receipt",
    "client_system_encryption_key",
}

CANONICAL_FOUNDATION_COLUMNS = {
    "client_enrollment_receipt": {
        "install_id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "resume_proof_hash": {"data_type": "character varying", "default": None, "length": 64, "nullable": False, "udt_name": "varchar"},
        "created_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "expires_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "completed_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
    },
    "client_system_encryption_key": {
        "id": {"data_type": "character varying", "default": None, "length": 64, "nullable": False, "udt_name": "varchar"},
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "algorithm": {"data_type": "character varying", "default": None, "length": 40, "nullable": False, "udt_name": "varchar"},
        "public_key_pem": {"data_type": "text", "default": None, "length": None, "nullable": False, "udt_name": "text"},
        "created_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "revoked_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
    },
}

CANONICAL_RETIRED_CLIENT_COLUMNS = {
    "school": {"data_type": "character varying", "default": None, "length": None, "nullable": True, "udt_name": "varchar"},
}

# These three definitions replace the Step-49A shared-domain constraints.
CANONICAL_FOUNDATION_CONSTRAINTS = {
    "ck_client_domain_credential_domain": "CHECK (domain::text = ANY (ARRAY['status'::character varying, 'display'::character varying, 'system'::character varying]::text[]))",
    "ck_client_domain_status_domain": "CHECK (domain::text = ANY (ARRAY['status'::character varying, 'display'::character varying, 'system'::character varying]::text[]))",
    "ck_client_command_domain": "CHECK (domain::text = ANY (ARRAY['display'::character varying, 'system'::character varying]::text[]))",
    "ck_client_enrollment_receipt_expiry": "CHECK (expires_at > created_at)",
    "client_enrollment_receipt_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES client(id)",
    "client_enrollment_receipt_pkey": "PRIMARY KEY (install_id)",
    "uq_client_enrollment_receipt_client": "UNIQUE (client_id)",
    "ck_client_system_encryption_key_algorithm": "CHECK (algorithm::text = 'RSA-OAEP-SHA256'::text)",
    "client_system_encryption_key_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES client(id)",
    "client_system_encryption_key_pkey": "PRIMARY KEY (id)",
    "uq_client_system_encryption_key_client": "UNIQUE (client_id)",
}

CANONICAL_FOUNDATION_INDEXES = {
    "client_enrollment_receipt_pkey": "CREATE UNIQUE INDEX client_enrollment_receipt_pkey ON public.client_enrollment_receipt USING btree (install_id)",
    "ix_client_enrollment_receipt_client_id": "CREATE INDEX ix_client_enrollment_receipt_client_id ON public.client_enrollment_receipt USING btree (client_id)",
    "ix_client_enrollment_receipt_completed_at": "CREATE INDEX ix_client_enrollment_receipt_completed_at ON public.client_enrollment_receipt USING btree (completed_at)",
    "ix_client_enrollment_receipt_expires_at": "CREATE INDEX ix_client_enrollment_receipt_expires_at ON public.client_enrollment_receipt USING btree (expires_at)",
    "ix_client_enrollment_receipt_expiry": "CREATE INDEX ix_client_enrollment_receipt_expiry ON public.client_enrollment_receipt USING btree (expires_at, completed_at)",
    "uq_client_enrollment_receipt_client": "CREATE UNIQUE INDEX uq_client_enrollment_receipt_client ON public.client_enrollment_receipt USING btree (client_id)",
    "client_system_encryption_key_pkey": "CREATE UNIQUE INDEX client_system_encryption_key_pkey ON public.client_system_encryption_key USING btree (id)",
    "ix_client_system_encryption_key_active": "CREATE INDEX ix_client_system_encryption_key_active ON public.client_system_encryption_key USING btree (client_id, revoked_at)",
    "ix_client_system_encryption_key_client_id": "CREATE INDEX ix_client_system_encryption_key_client_id ON public.client_system_encryption_key USING btree (client_id)",
    "ix_client_system_encryption_key_revoked_at": "CREATE INDEX ix_client_system_encryption_key_revoked_at ON public.client_system_encryption_key USING btree (revoked_at)",
    "uq_client_system_encryption_key_client": "CREATE UNIQUE INDEX uq_client_system_encryption_key_client ON public.client_system_encryption_key USING btree (client_id)",
}
