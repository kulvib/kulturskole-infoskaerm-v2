"""Shared data-only constants. No domain control logic belongs here."""
from __future__ import annotations

from enum import StrEnum

from .version import VERSION


class Domain(StrEnum):
    STATUS = "status"
    DISPLAY = "display"
    LIVESTREAM = "livestream"
    REMOTE_DESKTOP = "remote_desktop"
    TERMINAL = "terminal"
    SYSTEM = "system"


DOMAIN_VALUES = frozenset(item.value for item in Domain)
AGENT_VERSION = VERSION
DEFAULT_HTTP_TIMEOUT = 20.0
SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS = 15
# Legacy 1.1.19 polled backend config/actions every five seconds.  Keep the
# shared Display/System command consumer at the same idle cadence: it materially
# cuts always-on database work while preserving the proven legacy reaction
# envelope. Status reporting remains the separately reviewed 15-second contract.
SHARED_DOMAIN_COMMAND_POLL_SECONDS = 5.0
MAX_JSON_BYTES = 4 * 1024 * 1024
