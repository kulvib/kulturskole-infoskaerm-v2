"""Step 55A durable fresh-install enrollment release-binding schema delta."""

ENROLLMENT_BINDING_COLUMNS = {
    "fresh_install_release_id": {
        "data_type": "character varying",
        "default": None,
        "length": 160,
        "nullable": True,
        "udt_name": "varchar",
    },
    "fresh_install_version": {
        "data_type": "character varying",
        "default": None,
        "length": 32,
        "nullable": True,
        "udt_name": "varchar",
    },
    "fresh_install_release_sequence": {
        "data_type": "integer",
        "default": None,
        "length": None,
        "nullable": True,
        "udt_name": "int4",
    },
    "fresh_install_bundle_sha256": {
        "data_type": "character varying",
        "default": None,
        "length": 64,
        "nullable": True,
        "udt_name": "varchar",
    },
    "fresh_install_bundle_size": {
        "data_type": "integer",
        "default": None,
        "length": None,
        "nullable": True,
        "udt_name": "int4",
    },
    "fresh_install_approval_reference": {
        "data_type": "character varying",
        "default": None,
        "length": 200,
        "nullable": True,
        "udt_name": "varchar",
    },
    "fresh_install_candidate_sha256": {
        "data_type": "character varying",
        "default": None,
        "length": 64,
        "nullable": True,
        "udt_name": "varchar",
    },
    "fresh_install_source_commit": {
        "data_type": "character varying",
        "default": None,
        "length": 40,
        "nullable": True,
        "udt_name": "varchar",
    },
}
