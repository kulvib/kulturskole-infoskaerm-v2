from __future__ import annotations

PRODUCT = "ClientFlow"
MANIFEST_SCHEMA = 7
CHANNEL = "clientflow-runtime-release"
INTEGRITY_ALGORITHM = "sha256"
ARTIFACT_TYPE_RUNTIME_RELEASE = "runtime_release"
INSTALL_MODE_FRESH = "fresh_install"
INSTALL_MODE_UPDATE = "in_place_update"
MAX_BUNDLE_BYTES = 2 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FRESH_INSTALLER_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD_FILES = 20_000
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 1024 * 1024 * 1024
MAX_PATH_LENGTH = 240
DOMAIN_NAMES = (
    "status",
    "display",
    "livestream",
    "remote_desktop",
    "terminal",
    "system",
)
