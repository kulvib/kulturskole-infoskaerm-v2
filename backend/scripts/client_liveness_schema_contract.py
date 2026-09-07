"""Step 52A canonical client-liveness schema delta."""

CLIENT_LIVENESS_RETIRED_CLIENT_COLUMNS = {
    "isOnline": {"data_type": "boolean", "default": "false", "length": None, "nullable": True, "udt_name": "bool"},
    "last_seen": {"data_type": "timestamp without time zone", "default": None, "length": None, "nullable": True, "udt_name": "timestamp"},
}
