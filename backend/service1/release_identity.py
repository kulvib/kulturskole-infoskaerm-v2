"""Read-only runtime release identity for deployed PlanIQ services."""
from __future__ import annotations

import os
import re
from collections.abc import Mapping

_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ReleaseIdentityUnavailable(RuntimeError):
    """Raised when Render has not exposed a valid deployed commit."""


def resolve_release_commit(environment: Mapping[str, str] | None = None) -> str:
    """Return Render's full deployed Git SHA without exposing invalid raw input."""
    source = os.environ if environment is None else environment
    candidate = str(source.get("RENDER_GIT_COMMIT", "")).strip().lower()
    if not _FULL_GIT_SHA.fullmatch(candidate):
        raise ReleaseIdentityUnavailable("release identity unavailable")
    return candidate


def build_release_identity(
    product: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the stable public backend release payload."""
    name = str(product).strip()
    if not name:
        raise ReleaseIdentityUnavailable("release identity unavailable")
    return {
        "product": name,
        "component": "backend",
        "commit": resolve_release_commit(environment),
    }
