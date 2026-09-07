"""Sikker request-korrelation og fejlrespons til PlanIQ Display.

Modulet logger aldrig request body, headers, cookies, query string eller den rå
exceptiontekst. Det gør Render-loggen søgbar med et request-id uden at kopiere
credentials eller persondata ind i driftsloggen.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
import logging
from pathlib import Path
import re
import traceback
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_request_id_context: ContextVar[str | None] = ContextVar("planiq_request_id", default=None)


def _new_request_id() -> str:
    return uuid4().hex


def bind_request_id(request: Request) -> tuple[str, Token[str | None]]:
    """Bind et valideret eller nyt request-id til request og async context."""
    incoming = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
    request_id = incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else _new_request_id()
    request.state.request_id = request_id
    token = _request_id_context.set(request_id)
    return request_id, token


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_context.reset(token)


def get_bound_request_id(request: Request | None = None) -> str | None:
    """Returnér kun et allerede valideret request-id; opret aldrig et nyt."""
    if request is not None:
        request_id = getattr(request.state, "request_id", None)
        if isinstance(request_id, str) and _REQUEST_ID_PATTERN.fullmatch(request_id):
            return request_id

    request_id = _request_id_context.get()
    if isinstance(request_id, str) and _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    return None


def get_request_id(request: Request | None = None) -> str:
    """Hent request-id uden at stole på uvaliderede requestdata."""
    request_id = get_bound_request_id(request)
    if request_id is not None:
        return request_id

    request_id = _new_request_id()
    if request is not None:
        request.state.request_id = request_id
    return request_id


def add_request_id_header(response: Response, request_id: str) -> Response:
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def json_error_response(
    request: Request,
    *,
    status_code: int,
    error: str,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Byg en neutral fejlrespons med samme id som Render-loggen."""
    request_id = get_request_id(request)
    content: dict[str, Any] = {
        "detail": detail,
        "error": error,
        "request_id": request_id,
    }
    if extra:
        content.update(extra)
    response = JSONResponse(status_code=status_code, content=content)
    return add_request_id_header(response, request_id)


def safe_traceback_location(exc: BaseException, limit: int = 8) -> str:
    """Returnér kun filnavn, funktion og linje — aldrig exceptiontekst/data."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "unknown"
    safe_frames = frames[-limit:]
    return " > ".join(
        f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
        for frame in safe_frames
    )


def _safe_context_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return re.sub(r"[\r\n\t]+", "_", str(value))[:160]


def log_safe_exception(
    logger: logging.Logger,
    exc: BaseException,
    *,
    event: str,
    level: int = logging.ERROR,
    **context: Any,
) -> None:
    """Log en fejl uden rå exceptiontekst, traceback-indhold eller requestdata.

    Kaldere må kun sende dataminimerede korrelationsfelter som numeriske id'er,
    rolle, connection-id eller session-id i ``context``. Et allerede valideret
    request-id tilføjes automatisk, når fejlen sker i en HTTP-request.
    """
    fields: list[str] = [str(event)]
    request_id = get_bound_request_id()
    if request_id:
        fields.append(f"request_id={request_id}")
    for key, value in context.items():
        if value is None:
            continue
        safe_key = re.sub(r"[^A-Za-z0-9_]+", "_", str(key)).strip("_")
        if not safe_key:
            continue
        fields.append(f"{safe_key}={_safe_context_value(value)}")
    fields.append(f"error_type={type(exc).__name__}")
    fields.append(f"location={safe_traceback_location(exc)}")
    logger.log(level, " ".join(fields))


def log_unexpected_exception(
    logger: logging.Logger,
    request: Request,
    exc: BaseException,
    *,
    status_code: int,
    event: str,
    level: int = logging.ERROR,
) -> None:
    """Log en søgbar, men dataminimeret fejl uden rå exceptiontekst."""
    logger.log(
        level,
        "%s request_id=%s method=%s path=%s status_code=%s error_type=%s location=%s",
        event,
        get_request_id(request),
        request.method,
        request.url.path,
        status_code,
        type(exc).__name__,
        safe_traceback_location(exc),
    )
