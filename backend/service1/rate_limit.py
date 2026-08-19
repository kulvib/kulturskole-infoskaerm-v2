"""Shared abuse-protection contract for PlanIQ HTTP endpoints.

The limiter uses a fixed window and hashed keys. A Redis/Valkey-compatible
``REDIS_URL`` shares counters across workers and instances. Without it, the
module uses a deterministic in-process fallback suitable for one worker.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import math
import os
import threading
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from .client_ip import get_client_ip
from .observability import get_request_id, json_error_response, log_safe_exception

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "").strip()
RATE_LIMIT_NAMESPACE = os.getenv("RATE_LIMIT_NAMESPACE", "planiq").strip() or "planiq"
RATE_LIMIT_REDIS_REQUIRED = os.getenv("RATE_LIMIT_REDIS_REQUIRED", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
RATE_LIMIT_MEMORY_MAX_KEYS = max(100, int(os.getenv("RATE_LIMIT_MEMORY_MAX_KEYS", "10000")))


@dataclass(frozen=True)
class RateLimitState:
    count: int
    retry_after: int


class RateLimitExceeded(Exception):
    def __init__(self, *, bucket: str, retry_after: int, detail: str):
        super().__init__(detail)
        self.bucket = bucket
        self.retry_after = max(1, int(retry_after))
        self.detail = detail


_memory_lock = threading.Lock()
_memory_windows: dict[str, tuple[int, float]] = {}
_memory_operations = 0
_redis_client = None


def _safe_namespace(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)[:80]


def _storage_key(bucket: str, key: str) -> str:
    digest = hashlib.sha256(str(key or "unknown").encode("utf-8")).hexdigest()
    return f"{_safe_namespace(RATE_LIMIT_NAMESPACE)}:ratelimit:{_safe_namespace(bucket)}:{digest}"


if REDIS_URL:
    try:
        import redis  # type: ignore

        _redis_client = redis.Redis.from_url(
            REDIS_URL,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
        _redis_client.ping()
        logger.info("rate_limit_storage=redis namespace=%s", _safe_namespace(RATE_LIMIT_NAMESPACE))
    except Exception as exc:
        log_safe_exception(
            logger,
            exc,
            event="rate_limit_redis_unavailable",
            level=logging.WARNING,
            fallback="memory",
        )
        _redis_client = None

if RATE_LIMIT_REDIS_REQUIRED and _redis_client is None:
    raise RuntimeError("REDIS_URL skal være tilgængelig når RATE_LIMIT_REDIS_REQUIRED=true")


_REDIS_HIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


def _prune_memory_windows(now: float) -> None:
    expired = [key for key, (_, expires_at) in _memory_windows.items() if expires_at <= now]
    for key in expired:
        _memory_windows.pop(key, None)

    overflow = len(_memory_windows) - RATE_LIMIT_MEMORY_MAX_KEYS + 1
    if overflow > 0:
        oldest = sorted(_memory_windows, key=lambda key: _memory_windows[key][1])[:overflow]
        for key in oldest:
            _memory_windows.pop(key, None)


def _memory_state(storage_key: str, window_seconds: int, *, increment: bool) -> RateLimitState:
    global _memory_operations
    now = time.monotonic()
    with _memory_lock:
        _memory_operations += 1
        if increment and (
            len(_memory_windows) >= RATE_LIMIT_MEMORY_MAX_KEYS
            or _memory_operations % 256 == 0
        ):
            _prune_memory_windows(now)

        count, expires_at = _memory_windows.get(storage_key, (0, now + window_seconds))
        if expires_at <= now:
            count, expires_at = 0, now + window_seconds
        if increment:
            count += 1
            _memory_windows[storage_key] = (count, expires_at)
        elif count == 0:
            _memory_windows.pop(storage_key, None)
        retry_after = max(1, math.ceil(expires_at - now))
        return RateLimitState(count=count, retry_after=retry_after)


def _redis_state(storage_key: str, window_seconds: int, *, increment: bool) -> RateLimitState:
    if _redis_client is None:
        return _memory_state(storage_key, window_seconds, increment=increment)
    try:
        if increment:
            count, ttl = _redis_client.eval(_REDIS_HIT_SCRIPT, 1, storage_key, window_seconds)
            retry_after = int(ttl) if int(ttl) > 0 else window_seconds
            return RateLimitState(count=int(count), retry_after=max(1, retry_after))
        raw_count = _redis_client.get(storage_key)
        if raw_count is None:
            return RateLimitState(count=0, retry_after=window_seconds)
        ttl = int(_redis_client.ttl(storage_key))
        return RateLimitState(count=int(raw_count), retry_after=max(1, ttl if ttl > 0 else window_seconds))
    except Exception as exc:
        log_safe_exception(
            logger,
            exc,
            event="rate_limit_redis_operation_failed",
            level=logging.WARNING,
            fallback="error" if RATE_LIMIT_REDIS_REQUIRED else "memory",
        )
        if RATE_LIMIT_REDIS_REQUIRED:
            raise RuntimeError("Påkrævet rate-limit storage er utilgængelig") from exc
        return _memory_state(storage_key, window_seconds, increment=increment)


def _state(bucket: str, key: str, window_seconds: int, *, increment: bool) -> RateLimitState:
    if window_seconds < 1:
        raise ValueError("window_seconds skal være mindst 1")
    return _redis_state(_storage_key(bucket, key), window_seconds, increment=increment)


def enforce_key_rate_limit(
    *,
    bucket: str,
    key: str,
    max_attempts: int,
    window_seconds: int,
    detail: Optional[str] = None,
) -> None:
    """Record one request and reject attempts above the configured maximum."""
    if max_attempts < 1:
        raise ValueError("max_attempts skal være mindst 1")
    state = _state(bucket, key, window_seconds, increment=True)
    if state.count > max_attempts:
        raise RateLimitExceeded(
            bucket=bucket,
            retry_after=state.retry_after,
            detail=detail or "For mange forespørgsler. Prøv igen senere.",
        )


def enforce_request_rate_limit(
    request: Request,
    *,
    bucket: str,
    max_attempts: int,
    window_seconds: int,
    detail: Optional[str] = None,
) -> None:
    enforce_key_rate_limit(
        bucket=bucket,
        key=get_client_ip(request),
        max_attempts=max_attempts,
        window_seconds=window_seconds,
        detail=detail,
    )


def assert_key_not_limited(
    *,
    bucket: str,
    key: str,
    max_attempts: int,
    window_seconds: int,
    detail: Optional[str] = None,
) -> None:
    """Reject when previous recorded failures reached the configured maximum."""
    state = _state(bucket, key, window_seconds, increment=False)
    if state.count >= max_attempts:
        raise RateLimitExceeded(
            bucket=bucket,
            retry_after=state.retry_after,
            detail=detail or "For mange mislykkede forsøg. Prøv igen senere.",
        )


def record_key_attempt(*, bucket: str, key: str, window_seconds: int) -> None:
    _state(bucket, key, window_seconds, increment=True)


def clear_key_rate_limit(*, bucket: str, key: str) -> None:
    storage_key = _storage_key(bucket, key)
    if _redis_client is not None:
        try:
            _redis_client.delete(storage_key)
        except Exception as exc:
            log_safe_exception(
                logger,
                exc,
                event="rate_limit_redis_clear_failed",
                level=logging.WARNING,
            )
    with _memory_lock:
        _memory_windows.pop(storage_key, None)


def normalize_rate_limit_identifier(value: str | None) -> str:
    return (value or "").strip().casefold()[:320] or "unknown"


async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    logger.warning(
        "rate_limit_exceeded request_id=%s method=%s path=%s bucket=%s retry_after=%s cf_ray=%s",
        get_request_id(request),
        request.method,
        request.url.path,
        exc.bucket,
        exc.retry_after,
        (request.headers.get("cf-ray") or "-")[:80],
    )
    response = json_error_response(
        request,
        status_code=429,
        error="rate_limit_exceeded",
        detail=exc.detail,
        extra={"retry_after": exc.retry_after},
    )
    response.headers["Retry-After"] = str(exc.retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response


def _reset_rate_limit_state_for_tests() -> None:
    """Test helper; never used by production code."""
    global _memory_operations
    with _memory_lock:
        _memory_windows.clear()
        _memory_operations = 0
