"""Step 54A Display operational-parity schema delta."""

DISPLAY_OPERATIONAL_PARITY_COLUMNS = {
    "browser_refresh_interval_sec": {
        "data_type": "integer",
        "default": "900",
        "length": None,
        "nullable": False,
        "udt_name": "int4",
    },
}

DISPLAY_OPERATIONAL_PARITY_CONSTRAINTS = {
    "ck_display_desired_configuration_browser_refresh_interval": (
        "CHECK (((browser_refresh_interval_sec = 0) OR "
        "((browser_refresh_interval_sec >= 60) AND (browser_refresh_interval_sec <= 86400))))"
    ),
}
