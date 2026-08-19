"""SMTP-mailhjælper til PlanIQ Display systemmails.

Bruger kun Python standardbiblioteket. SMTP_* værdierne læses fra
miljøvariabler, så der ikke tilføjes nye backend dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html import unescape
from typing import Optional

from .branding import MAIL_FROM_NAME
from .observability import log_safe_exception

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    secure: bool
    username: str
    password: str
    from_header: str
    from_address: str


def _clean_header(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if "\r" in cleaned or "\n" in cleaned:
        raise ValueError("SMTP-header indeholder ulovlige linjeskift")
    return cleaned


def _extract_address_and_name(value: str) -> tuple[str, str]:
    raw = unescape((value or "").strip())
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1].strip()

    if "<" in raw and ">" in raw:
        display_name = raw.split("<", 1)[0].strip().strip('"').strip("'")
        address = raw.split("<", 1)[1].split(">", 1)[0].strip()
    else:
        display_name, address = parseaddr(raw)
        display_name = (display_name or "").strip().strip('"').strip("'")
        address = (address or "").strip()

    if not address or "@" not in address or "<" in address or ">" in address:
        raise ValueError("SMTP_FROM skal indeholde en gyldig afsenderadresse")
    if "\r" in address or "\n" in address or "\r" in display_name or "\n" in display_name:
        raise ValueError("SMTP_FROM indeholder ulovlige linjeskift")
    return display_name, address


def _format_from(value: str) -> str:
    display_name, address = _extract_address_and_name(value)
    display_name = display_name or MAIL_FROM_NAME
    return formataddr((display_name, address))


def _address_only(value: str) -> str:
    _display_name, address = _extract_address_and_name(value)
    return address


def get_smtp_config() -> SmtpConfig:
    host = _clean_header(os.getenv("SMTP_HOST"))
    username = _clean_header(os.getenv("SMTP_USER"))
    password = os.getenv("SMTP_PASS") or ""
    from_header = _clean_header(os.getenv("SMTP_FROM"))

    if not host or not username or not password or not from_header:
        raise RuntimeError(
            "SMTP er ikke konfigureret. Tjek SMTP_HOST, SMTP_USER, SMTP_PASS og SMTP_FROM i Render."
        )

    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT skal være et tal") from exc

    secure = os.getenv("SMTP_SECURE", "false").strip().lower() in {"1", "true", "yes", "ja"}
    from_address = _address_only(from_header)

    return SmtpConfig(
        host=host,
        port=port,
        secure=secure,
        username=username,
        password=password,
        from_header=_format_from(from_header),
        from_address=from_address,
    )


def _send_email_sync(*, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
    cfg = get_smtp_config()

    clean_to = _clean_header(to)
    clean_subject = _clean_header(subject)
    if not clean_to or not clean_subject:
        raise ValueError("Modtager og emne skal udfyldes")

    msg = EmailMessage()
    msg["From"] = cfg.from_header
    msg["To"] = clean_to
    msg["Subject"] = clean_subject

    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if cfg.secure:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20, context=context) as server:
            server.login(cfg.username, cfg.password)
            server.send_message(msg, from_addr=cfg.from_address)
    else:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg.host, cfg.port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(cfg.username, cfg.password)
            server.send_message(msg, from_addr=cfg.from_address)


async def send_email(*, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
    try:
        await asyncio.to_thread(_send_email_sync, to=to, subject=subject, text=text, html=html)
    except Exception as exc:
        log_safe_exception(
            logger,
            exc,
            event="system_email_send_failed",
            recipient_present=bool(to),
        )
        raise
