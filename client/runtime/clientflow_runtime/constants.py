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
MAX_JSON_BYTES = 4 * 1024 * 1024
