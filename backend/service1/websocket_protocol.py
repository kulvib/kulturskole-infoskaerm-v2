"""Shared WebSocket protocol primitives.

The public ClientFlow message shapes remain dictionaries on the wire.  This
module centralises defensive decoding, message-type validation and bounded
string handling so each broker applies the same limits and error semantics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Collection, Mapping


class ProtocolError(ValueError):
    """A client-visible WebSocket protocol violation."""

    def __init__(self, message: str, *, close_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.close_code = close_code


@dataclass(frozen=True)
class DecodedMessage:
    type: str
    payload: dict[str, Any]


def decode_json_message(
    raw: str,
    *,
    allowed_types: Collection[str] | None = None,
    max_chars: int = 2_100_000,
    unknown_type_prefix: str = "Ukendt type",
) -> DecodedMessage:
    if len(raw) > max_chars:
        raise ProtocolError("WebSocket-beskeden er for stor", close_code=1009)
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Ugyldig JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("WebSocket-beskeden skal være et JSON-objekt")
    message_type = value.get("type")
    if not isinstance(message_type, str) or not message_type.strip():
        raise ProtocolError("WebSocket-beskeden mangler type")
    message_type = message_type.strip()
    if allowed_types is not None and message_type not in allowed_types:
        raise ProtocolError(f"{unknown_type_prefix}: {message_type}")
    value["type"] = message_type
    return DecodedMessage(type=message_type, payload=value)


def bounded_text(
    payload: Mapping[str, Any],
    field: str,
    *,
    maximum: int,
    default: str = "",
    required: bool = False,
    strip: bool = False,
    too_long_message: str | None = None,
    missing_message: str | None = None,
) -> str:
    value = payload.get(field)
    text = default if value is None else str(value)
    if strip:
        text = text.strip()
    if required and not text:
        raise ProtocolError(missing_message or f"{field} mangler")
    if len(text) > maximum:
        raise ProtocolError(too_long_message or f"{field} er for langt")
    return text


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))
