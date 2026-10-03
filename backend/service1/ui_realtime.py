"""DB-free browser wake channel for Control Room live state.

A short-lived capability is issued after normal application authentication. The
capability carries only scope metadata and lets the browser block on a process-
local generation without holding a PostgreSQL session. The wake carries no
client data; authoritative snapshots are still fetched through normal protected
HTTP endpoints after a change.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import os
import threading
import time
import uuid
from typing import Any

import jwt
from fastapi import HTTPException, status

from .auth import SECRET_KEY

ISSUER = "clientflow-ui-realtime"
AUDIENCE = "clientflow-ui-realtime"
TTL_SECONDS = min(max(120, int(os.getenv("CLIENTFLOW_UI_REALTIME_CAPABILITY_TTL_SECONDS", "300"))), 900)
_CONDITION = threading.Condition()
_GLOBAL_GENERATION = 0
_ORG_GENERATIONS: dict[int, int] = defaultdict(int)


def _scope_for_principal(principal: object) -> tuple[bool, int | None]:
    is_global = bool(getattr(principal, "is_superadmin", False) or getattr(principal, "role", None) == "viewer")
    organization_id = getattr(principal, "organization_id", None)
    if not is_global and organization_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Realtime-scope mangler organisation")
    return is_global, int(organization_id) if organization_id is not None else None


def current_generation(*, global_scope: bool, organization_id: int | None) -> int:
    with _CONDITION:
        if global_scope:
            return int(_GLOBAL_GENERATION)
        if organization_id is None:
            raise ValueError("organization_id kræves for organisationsscope")
        return int(_ORG_GENERATIONS[int(organization_id)])


def notify_ui_state_changed(*, organization_id: int | None) -> int:
    global _GLOBAL_GENERATION
    with _CONDITION:
        _GLOBAL_GENERATION += 1
        if organization_id is not None:
            _ORG_GENERATIONS[int(organization_id)] += 1
            generation = int(_ORG_GENERATIONS[int(organization_id)])
        else:
            generation = int(_GLOBAL_GENERATION)
        _CONDITION.notify_all()
        return generation


def issue_ui_realtime_capability(principal: object) -> dict[str, Any]:
    global_scope, organization_id = _scope_for_principal(principal)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=TTL_SECONDS)
    principal_id = getattr(principal, "id", None)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": f"ui-realtime:{principal_id}",
        "purpose": "ui_realtime_wait",
        "principal_id": str(principal_id),
        "global_scope": global_scope,
        "organization_id": organization_id,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, SECRET_KEY, algorithm="HS256")
    return {
        "capability": token,
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "ttl_seconds": TTL_SECONDS,
        "generation": current_generation(global_scope=global_scope, organization_id=organization_id),
    }


def verify_ui_realtime_capability(token: str | None) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Realtime-capability mangler")
    try:
        claims = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "nbf", "jti", "sub", "purpose", "principal_id"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ugyldig realtime-capability") from exc
    if claims.get("purpose") != "ui_realtime_wait":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forkert realtime-capability")
    if not bool(claims.get("global_scope")) and claims.get("organization_id") is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Realtime-capability mangler scope")
    return claims


def wait_for_ui_change(*, claims: dict[str, Any], after: int, timeout: float) -> int:
    global_scope = bool(claims.get("global_scope"))
    organization_id = claims.get("organization_id")
    organization_id = int(organization_id) if organization_id is not None else None
    deadline = time.monotonic() + min(max(float(timeout), 0.0), 30.0)
    with _CONDITION:
        while current_generation(global_scope=global_scope, organization_id=organization_id) <= int(after):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _CONDITION.wait(timeout=remaining)
        return current_generation(global_scope=global_scope, organization_id=organization_id)
