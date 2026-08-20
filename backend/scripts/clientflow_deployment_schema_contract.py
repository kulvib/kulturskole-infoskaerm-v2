"""Exact Step 51A first-class ClientFlow deployment schema contract."""

CLIENTFLOW_DEPLOYMENT_TABLES = {
    "clientflow_update_credential",
    "clientflow_deployment",
    "clientflow_deployment_event",
}

CLIENTFLOW_DEPLOYMENT_COLUMNS = {
    "clientflow_update_credential": {
        "id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "key_id": {"data_type": "character varying", "default": None, "length": 64, "nullable": False, "udt_name": "varchar"},
        "public_key_pem": {"data_type": "text", "default": None, "length": None, "nullable": False, "udt_name": "text"},
        "algorithm": {"data_type": "character varying", "default": None, "length": 20, "nullable": False, "udt_name": "varchar"},
        "created_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "last_used_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
        "revoked_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
        "rotated_from_credential_id": {"data_type": "character varying", "default": None, "length": 36, "nullable": True, "udt_name": "varchar"},
    },
    "clientflow_deployment": {
        "id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "client_id": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "target_release_id": {"data_type": "character varying", "default": None, "length": 160, "nullable": False, "udt_name": "varchar"},
        "target_version": {"data_type": "character varying", "default": None, "length": 40, "nullable": False, "udt_name": "varchar"},
        "target_release_sequence": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "bundle_sha256": {"data_type": "character varying", "default": None, "length": 64, "nullable": False, "udt_name": "varchar"},
        "bundle_size": {"data_type": "integer", "default": None, "length": None, "nullable": False, "udt_name": "int4"},
        "release_approval_reference": {"data_type": "character varying", "default": None, "length": 200, "nullable": False, "udt_name": "varchar"},
        "release_candidate_sha256": {"data_type": "character varying", "default": None, "length": 64, "nullable": True, "udt_name": "varchar"},
        "source_commit": {"data_type": "character varying", "default": None, "length": 64, "nullable": True, "udt_name": "varchar"},
        "allow_downgrade": {"data_type": "boolean", "default": "false", "length": None, "nullable": False, "udt_name": "bool"},
        "reason": {"data_type": "text", "default": None, "length": None, "nullable": True, "udt_name": "text"},
        "requested_by_user_id": {"data_type": "integer", "default": None, "length": None, "nullable": True, "udt_name": "int4"},
        "requested_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "state": {"data_type": "character varying", "default": "'authorized'::character varying", "length": 32, "nullable": False, "udt_name": "varchar"},
        "state_updated_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "completed_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
        "observed_previous_release_id": {"data_type": "character varying", "default": None, "length": 160, "nullable": True, "udt_name": "varchar"},
        "observed_release_id": {"data_type": "character varying", "default": None, "length": 160, "nullable": True, "udt_name": "varchar"},
        "observed_release_sequence": {"data_type": "integer", "default": None, "length": None, "nullable": True, "udt_name": "int4"},
        "failure_code": {"data_type": "character varying", "default": None, "length": 100, "nullable": True, "udt_name": "varchar"},
        "failure_message": {"data_type": "text", "default": None, "length": None, "nullable": True, "udt_name": "text"},
    },
    "clientflow_deployment_event": {
        "id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "deployment_id": {"data_type": "character varying", "default": None, "length": 36, "nullable": False, "udt_name": "varchar"},
        "credential_id": {"data_type": "character varying", "default": None, "length": 36, "nullable": True, "udt_name": "varchar"},
        "event_type": {"data_type": "character varying", "default": None, "length": 80, "nullable": False, "udt_name": "varchar"},
        "occurred_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
        "received_at": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": False, "udt_name": "timestamp"},
        "payload": {"data_type": "jsonb", "default": None, "length": None, "nullable": False, "udt_name": "jsonb"},
    },
}

CLIENTFLOW_DEPLOYMENT_CONSTRAINTS = {
    "ck_clientflow_update_credential_algorithm": "CHECK (algorithm::text = 'Ed25519'::text)",
    "clientflow_update_credential_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES client(id)",
    "clientflow_update_credential_rotated_from_credential_id_fkey": "FOREIGN KEY (rotated_from_credential_id) REFERENCES clientflow_update_credential(id) ON DELETE SET NULL",
    "clientflow_update_credential_pkey": "PRIMARY KEY (id)",
    "ck_clientflow_deployment_release_sequence": "CHECK (target_release_sequence > 0)",
    "ck_clientflow_deployment_bundle_size": "CHECK (bundle_size > 0)",
    "ck_clientflow_deployment_bundle_sha256": "CHECK (length(bundle_sha256::text) = 64)",
    "clientflow_deployment_client_id_fkey": "FOREIGN KEY (client_id) REFERENCES client(id)",
    "clientflow_deployment_requested_by_user_id_fkey": 'FOREIGN KEY (requested_by_user_id) REFERENCES "user"(id) ON DELETE SET NULL',
    "clientflow_deployment_pkey": "PRIMARY KEY (id)",
    "clientflow_deployment_event_deployment_id_fkey": "FOREIGN KEY (deployment_id) REFERENCES clientflow_deployment(id) ON DELETE CASCADE",
    "clientflow_deployment_event_credential_id_fkey": "FOREIGN KEY (credential_id) REFERENCES clientflow_update_credential(id) ON DELETE SET NULL",
    "clientflow_deployment_event_pkey": "PRIMARY KEY (id)",
}

# State/completion/boolean CHECK definitions are appended below as literal
# expected PostgreSQL deparsing.  They remain named and therefore fail closed
# if their semantics change.
CLIENTFLOW_DEPLOYMENT_CONSTRAINTS.update({
    "ck_clientflow_deployment_state": "CHECK (state::text = ANY (ARRAY['authorized'::character varying::text, 'downloading'::character varying::text, 'verified'::character varying::text, 'staged'::character varying::text, 'activating'::character varying::text, 'health_check'::character varying::text, 'succeeded'::character varying::text, 'failed'::character varying::text, 'cancelled'::character varying::text, 'rolling_back'::character varying::text, 'rolled_back'::character varying::text, 'recovery_failed'::character varying::text]))",
    "ck_clientflow_deployment_completion": "CHECK ((state::text = ANY (ARRAY['succeeded'::character varying::text, 'failed'::character varying::text, 'cancelled'::character varying::text, 'rolled_back'::character varying::text, 'recovery_failed'::character varying::text])) AND completed_at IS NOT NULL OR (state::text <> ALL (ARRAY['succeeded'::character varying::text, 'failed'::character varying::text, 'cancelled'::character varying::text, 'rolled_back'::character varying::text, 'recovery_failed'::character varying::text])) AND completed_at IS NULL)",
    "ck_clientflow_deployment_downgrade_reason": "CHECK (allow_downgrade = false OR reason IS NOT NULL)",
})

CLIENTFLOW_DEPLOYMENT_INDEXES = {
    "clientflow_update_credential_pkey": "CREATE UNIQUE INDEX clientflow_update_credential_pkey ON public.clientflow_update_credential USING btree (id)",
    "ix_clientflow_update_credential_client_id": "CREATE INDEX ix_clientflow_update_credential_client_id ON public.clientflow_update_credential USING btree (client_id)",
    "ix_clientflow_update_credential_revoked_at": "CREATE INDEX ix_clientflow_update_credential_revoked_at ON public.clientflow_update_credential USING btree (revoked_at)",
    "uq_clientflow_update_credential_active_client": "CREATE UNIQUE INDEX uq_clientflow_update_credential_active_client ON public.clientflow_update_credential USING btree (client_id) WHERE (revoked_at IS NULL)",
    "uq_clientflow_update_credential_key_id": "CREATE UNIQUE INDEX uq_clientflow_update_credential_key_id ON public.clientflow_update_credential USING btree (key_id)",
    "clientflow_deployment_pkey": "CREATE UNIQUE INDEX clientflow_deployment_pkey ON public.clientflow_deployment USING btree (id)",
    "ix_clientflow_deployment_client_id": "CREATE INDEX ix_clientflow_deployment_client_id ON public.clientflow_deployment USING btree (client_id)",
    "ix_clientflow_deployment_requested_at": "CREATE INDEX ix_clientflow_deployment_requested_at ON public.clientflow_deployment USING btree (requested_at)",
    "ix_clientflow_deployment_state": "CREATE INDEX ix_clientflow_deployment_state ON public.clientflow_deployment USING btree (state)",
    "ix_clientflow_deployment_target_release": "CREATE INDEX ix_clientflow_deployment_target_release ON public.clientflow_deployment USING btree (target_release_id, target_release_sequence)",
    "uq_clientflow_deployment_active_client": "CREATE UNIQUE INDEX uq_clientflow_deployment_active_client ON public.clientflow_deployment USING btree (client_id) WHERE (completed_at IS NULL)",
    "clientflow_deployment_event_pkey": "CREATE UNIQUE INDEX clientflow_deployment_event_pkey ON public.clientflow_deployment_event USING btree (id)",
    "ix_clientflow_deployment_event_deployment_id": "CREATE INDEX ix_clientflow_deployment_event_deployment_id ON public.clientflow_deployment_event USING btree (deployment_id)",
    "ix_clientflow_deployment_event_received_at": "CREATE INDEX ix_clientflow_deployment_event_received_at ON public.clientflow_deployment_event USING btree (received_at)",
    "ix_clientflow_deployment_event_credential_id": "CREATE INDEX ix_clientflow_deployment_event_credential_id ON public.clientflow_deployment_event USING btree (credential_id)",
}
