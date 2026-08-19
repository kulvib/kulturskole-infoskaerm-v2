from __future__ import annotations

from pathlib import Path

PRODUCT = "ClientFlow"
MANIFEST_SCHEMA = 5
CHANNEL = "fresh-only-release"
INTEGRITY_ALGORITHM = "sha256"
DEFAULT_INSTALL_ROOT = Path("/opt/clientflow")
DEFAULT_ETC_ROOT = Path("/etc/clientflow")
DEFAULT_STATE_ROOT = Path("/var/lib/clientflow/release")
DEFAULT_INCOMING_ROOT = Path("/var/lib/clientflow/system-agent/incoming")
MAX_BUNDLE_BYTES = 2 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
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
MANAGED_UNIT_PREFIX = "clientflow-"
