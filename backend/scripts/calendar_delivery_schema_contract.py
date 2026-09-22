"""Step 56A lightweight Calendar delivery revision schema delta."""

CALENDAR_DELIVERY_COLUMNS = {
    "updated_at": {
        "data_type": "timestamp without time zone",
        "default": None,
        "length": None,
        "nullable": False,
        "udt_name": "timestamp",
    },
}
