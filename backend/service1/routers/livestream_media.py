"""Canonical read-only HLS media boundary for Livestream.

All control, viewer lifecycle and agent uploads live in ``routers.livestream_v2``.
This module only owns HLS storage path validation and browser-readable media
health/last-segment metadata.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from ..auth import get_current_user_or_client, principal_is_client, require_client_self_or_user
from ..db import engine
from ..models import Client
from ..observability import log_safe_exception

router = APIRouter()
logger_name = __name__
import logging
logger = logging.getLogger(logger_name)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HLS_DIR = os.path.abspath(os.getenv("HLS_BASE_DIR") or os.path.join(BASE_DIR, "..", "hls"))
os.makedirs(HLS_DIR, exist_ok=True)

MANIFEST_STALE_SECONDS = int(os.getenv("HLS_STALE_SECONDS", "60"))


def _apply_hls_no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


def safe_client_dir(client_id: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", str(client_id)):
        raise HTTPException(status_code=400, detail="Ugyldigt client_id format")
    path = os.path.abspath(os.path.join(HLS_DIR, str(client_id)))
    if os.path.commonpath([HLS_DIR, path]) != HLS_DIR:
        raise HTTPException(status_code=400, detail="Ugyldigt client_id")
    return path


def _is_hls_segment_name(name: str) -> bool:
    return bool(re.fullmatch(r"segment(?:_|-)\d+\.(?:ts|m4s|mp4)", name))


def _hls_stop_marker_path(client_id: str) -> str:
    return os.path.join(safe_client_dir(client_id), ".stream_stopped.json")


def _hls_stop_marker_exists(client_id: str) -> bool:
    return os.path.exists(_hls_stop_marker_path(str(client_id)))


def require_hls_access(principal, client_id: str) -> None:
    try:
        cid = int(client_id)
    except Exception as exc:
        raise HTTPException(status_code=403, detail="HLS kræver numerisk client_id") from exc

    with Session(engine) as session:
        client = session.get(Client, cid)
        if not client:
            raise HTTPException(status_code=404, detail="Klient ikke fundet")

        if principal_is_client(principal):
            require_client_self_or_user(principal, cid)
            if client.status != "approved":
                raise HTTPException(status_code=403, detail="Klienten er ikke godkendt")
            return
        if getattr(principal, "is_superadmin", False):
            return

        same_org = getattr(principal, "organization_id", None) == getattr(client, "organization_id", None)
        if getattr(principal, "is_admin", False) and same_org:
            return
        if getattr(principal, "role", None) in ("bruger", "viewer") and client.status == "approved" and same_org:
            return

    raise HTTPException(status_code=403, detail="Du har ikke adgang til denne HLS stream")


def _parse_program_date(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _read_manifest_program_dates(manifest_path: str) -> Dict[str, datetime]:
    out: Dict[str, datetime] = {}
    try:
        pending: Optional[datetime] = None
        with open(manifest_path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
                    pending = _parse_program_date(line.split(":", 1)[1])
                elif _is_hls_segment_name(line):
                    if pending is not None:
                        out[line] = pending
                    pending = None
    except OSError:
        pass
    return out


def _guess_target_duration(lines: list[str]) -> Optional[int]:
    for line in lines:
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                return int(line.split(":", 1)[1])
            except Exception:
                return None
    return None


@router.get("/hls/{client_id}/last-segment-info")
def get_last_segment_info(client_id: str, response: Response, user=Depends(get_current_user_or_client)):
    require_hls_access(user, client_id)
    _apply_hls_no_cache(response)
    client_dir = safe_client_dir(client_id)
    if _hls_stop_marker_exists(client_id):
        return {"error": "stream stopped", "is_healthy": False, "stream_stopped": True}

    manifest_path = os.path.join(client_dir, "index.m3u8")
    if not os.path.exists(manifest_path):
        return {"error": "no manifest", "is_healthy": False}
    with open(manifest_path, encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]
    segments = [line for line in lines if _is_hls_segment_name(line)]
    if not segments:
        return {"error": "no segments", "is_healthy": False}

    segment = segments[-1]
    seg_path = os.path.join(client_dir, segment)
    if not os.path.exists(seg_path):
        return {"error": "segment missing", "is_healthy": False}

    dt = _read_manifest_program_dates(manifest_path).get(segment)
    if dt is None:
        dt = datetime.fromtimestamp(os.path.getmtime(seg_path), tz=timezone.utc)
    return {
        "segment": segment,
        "timestamp": dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "epoch": dt.timestamp(),
        "segment_count": len(segments),
        "is_healthy": True,
    }


@router.get("/hls/{client_id}/health")
def health_check(client_id: str, response: Response, user=Depends(get_current_user_or_client)):
    require_hls_access(user, client_id)
    _apply_hls_no_cache(response)
    client_dir = safe_client_dir(client_id)
    if _hls_stop_marker_exists(client_id):
        return {"online": False, "has_segments": False, "is_stale": False, "last_update": None, "stream_stopped": True, "message": "Stream er stoppet"}

    manifest_path = os.path.join(client_dir, "index.m3u8")
    if not os.path.exists(manifest_path):
        return {"online": False, "has_segments": False, "is_stale": False, "last_update": None, "message": "Manifest ikke fundet"}
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        segments = [line for line in lines if _is_hls_segment_name(line)]
        existing = [name for name in segments if os.path.exists(os.path.join(client_dir, name)) and os.path.getsize(os.path.join(client_dir, name)) > 1000]
        if not existing:
            return {"online": True, "has_segments": False, "is_stale": False, "last_update": None, "segment_count": 0, "manifest_segment_count": len(segments), "message": "Manifest findes, men segmentfiler mangler"}
        latest = existing[-1]
        mtime = os.path.getmtime(os.path.join(client_dir, latest))
        age = time.time() - mtime
        stale = age > MANIFEST_STALE_SECONDS
        return {
            "online": True,
            "has_segments": True,
            "is_stale": stale,
            "stale_after_seconds": MANIFEST_STALE_SECONDS,
            "server_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "last_update": datetime.fromtimestamp(mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "age_seconds": round(age, 2),
            "segment_count": len(existing),
            "manifest_segment_count": len(segments),
            "latest_segment": latest,
            "target_duration": _guess_target_duration(lines),
            "message": "Stream er forældet — klienten svarer ikke" if stale else "Stream er aktiv",
        }
    except Exception as exc:
        log_safe_exception(logger, exc, event="hls_health_check_failed", level=logging.WARNING, client_id=client_id)
        return {"online": False, "has_segments": False, "is_stale": False, "last_update": None, "message": "Fejl ved health check"}
