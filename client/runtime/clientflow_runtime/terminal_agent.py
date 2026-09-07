"""Unprivileged Terminal network agent and local PTY bridge."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import json
import os
import ssl
import uuid
from contextlib import suppress
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from .config import DomainCredential
from .constants import Domain
from .logging_utils import configure_logging
from .terminal_net import DomainTransport, backoff_seconds
from .status import report_status

STANDARD_SOCKET = os.getenv("CLIENTFLOW_STANDARD_TERMINAL_SOCKET", "/run/clientflow/standard-terminal.sock")
ROOT_SOCKET = os.getenv("CLIENTFLOW_ROOT_TERMINAL_SOCKET", "/run/clientflow/root-terminal.sock")
MAX_INPUT_BYTES = 1024 * 1024


class BrokerProxy:
    def __init__(
        self,
        session_id: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        agent: "TerminalAgent",
    ) -> None:
        self.session_id = session_id
        self.reader = reader
        self.writer = writer
        self.agent = agent
        self.task: asyncio.Task[None] | None = None
        self._closed = False

    def start(self) -> None:
        if self.task is not None:
            raise RuntimeError("Terminalproxy er allerede startet")
        self.task = asyncio.create_task(self._read_loop())

    async def _send(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Rootbroker-meddelelsen er for stor")
        self.writer.write(raw)
        await self.writer.drain()

    async def _read_loop(self) -> None:
        try:
            while not self._closed:
                raw = await self.reader.readline()
                if not raw:
                    break
                if len(raw) > 4 * 1024 * 1024:
                    raise RuntimeError("Rootbroker-output er for stort")
                message = json.loads(raw)
                message_type = message.get("type")
                if message_type == "output":
                    await self.agent.send(
                        {
                            "type": "output",
                            "session_id": self.session_id,
                            "data": str(message.get("data_b64") or ""),
                            "encoding": "base64",
                        }
                    )
                elif message_type == "timeout":
                    await self.agent.report_event(self.session_id, "timeout")
                elif message_type == "exit":
                    reference = str(message.get("transcript_reference") or "") or None
                    digest = str(message.get("transcript_sha256") or "") or None
                    if reference and digest:
                        await self.agent.report_event(
                            self.session_id,
                            "transcript_stored",
                            transcript_reference=reference,
                            transcript_sha256=digest,
                        )
                    await self.agent.report_event(
                        self.session_id,
                        "pty_exited",
                        exit_code=int(message.get("exit_code", -1)),
                    )
                    await self.agent.send(
                        {
                            "type": "exit",
                            "session_id": self.session_id,
                            "exit_code": int(message.get("exit_code", -1)),
                        }
                    )
                    break
                elif message_type == "rejected":
                    await self.agent.report_event(
                        self.session_id,
                        "broker_rejected",
                        details={"error": str(message.get("error") or "rejected")[:500]},
                    )
                    await self.agent.send(
                        {"type": "error", "session_id": self.session_id, "error": "root_broker_rejected"}
                    )
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            self.agent.logger.exception("terminal_proxy_failed", extra={"session_id": self.session_id})
        finally:
            self._closed = True
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except OSError:
                pass
            self.agent.sessions.pop(self.session_id, None)

    async def input(self, payload: bytes) -> None:
        await self._send({"action": "input", "data_b64": base64.b64encode(payload).decode("ascii")})

    async def resize(self, cols: int, rows: int) -> None:
        await self._send({"action": "resize", "cols": cols, "rows": rows})

    async def signal(self, signal_name: str) -> None:
        await self._send({"action": "signal", "signal": signal_name})

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._send({"action": "close"})
        except (OSError, RuntimeError):
            pass
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except OSError:
            pass
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task


class TerminalAgent:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.terminal")
        self.credential = DomainCredential.load(Domain.TERMINAL)
        self.transport = DomainTransport(self.credential)
        self.websocket: Any = None
        self.send_lock = asyncio.Lock()
        self.sessions: dict[str, BrokerProxy] = {}

    def ssl_context(self) -> ssl.SSLContext | None:
        if not self.transport.websocket_url("/").startswith("wss:"):
            return None
        context = ssl.create_default_context(cafile=self.credential.tls_ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context

    async def send(self, payload: dict[str, Any]) -> None:
        if self.websocket is None:
            return
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        async with self.send_lock:
            await self.websocket.send(raw)

    async def report_event(
        self,
        session_id: str,
        event_type: str,
        *,
        details: dict[str, Any] | None = None,
        exit_code: int | None = None,
        transcript_reference: str | None = None,
        transcript_sha256: str | None = None,
    ) -> None:
        client_id = self.credential.client_id
        body = {
            "event_type": event_type,
            "details": details or {},
            "exit_code": exit_code,
            "transcript_reference": transcript_reference,
            "transcript_sha256": transcript_sha256,
        }
        await asyncio.to_thread(
            self.transport.json_request,
            "POST",
            f"/api/terminal-agent/clients/{client_id}/sessions/{session_id}/events",
            json_body=body,
        )

    def _timeout_from_expiry(self, raw: object, *, root: bool) -> int:
        try:
            expiry = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            remaining = int((expiry - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            remaining = 0
        maximum = 600 if root else 1800
        if remaining <= 0:
            raise ValueError("Terminalsessionen er udløbet")
        return min(remaining, maximum)

    async def _open_broker(
        self,
        *,
        session_id: str,
        socket_path: str,
        request: dict[str, Any],
        privilege_level: str,
    ) -> None:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), timeout=10)
        if not raw or len(raw) > 2 * 1024 * 1024:
            writer.close()
            await writer.wait_closed()
            raise RuntimeError("Terminalbroker returnerede ugyldigt svar")
        response = json.loads(raw)
        if response.get("type") != "accepted":
            writer.close()
            await writer.wait_closed()
            await self.report_event(session_id, "broker_rejected", details={"error": str(response)[:500]})
            raise RuntimeError("Terminalbroker afviste sessionen")
        proxy = BrokerProxy(session_id, reader, writer, self)
        self.sessions[session_id] = proxy
        proxy.start()
        try:
            if privilege_level == "root":
                await self.report_event(
                    session_id,
                    "root_grant_consumed",
                    details={"grant_id": str(response.get("grant_id") or "")},
                )
            await self.report_event(session_id, "pty_started")
            await self.send({"type": "ready", "session_id": session_id, "privilege_level": privilege_level})
        except Exception:
            self.sessions.pop(session_id, None)
            await proxy.close()
            raise

    async def _start_standard(self, message: dict[str, Any]) -> None:
        session_id = str(message.get("session_id") or "")
        timeout = self._timeout_from_expiry(message.get("expires_at"), root=False)
        await self._open_broker(
            session_id=session_id,
            socket_path=STANDARD_SOCKET,
            request={
                "action": "open",
                "session_id": session_id,
                "timeout_seconds": timeout,
                "cols": 120,
                "rows": 32,
            },
            privilege_level="standard",
        )

    async def _start_root(self, message: dict[str, Any]) -> None:
        session_id = str(message.get("session_id") or "")
        timeout = self._timeout_from_expiry(message.get("expires_at"), root=True)
        root_grant = str(message.get("root_grant") or "")
        if not root_grant:
            raise ValueError("Rootsessionen mangler root_grant")
        await self._open_broker(
            session_id=session_id,
            socket_path=ROOT_SOCKET,
            request={
                "action": "open",
                "session_id": session_id,
                "root_grant": root_grant,
                "timeout_seconds": timeout,
                "cols": 120,
                "rows": 32,
            },
            privilege_level="root",
        )

    async def _start_session(self, message: dict[str, Any]) -> None:
        session_id = str(message.get("session_id") or "")
        try:
            uuid.UUID(session_id)
        except ValueError as exc:
            raise ValueError("Terminalsessionen har ugyldigt ID") from exc
        if session_id in self.sessions:
            raise ValueError("Terminalsessionen er allerede aktiv")
        privilege = str(message.get("privilege_level") or "")
        if privilege == "standard":
            await self._start_standard(message)
        elif privilege == "root":
            await self._start_root(message)
        else:
            raise ValueError("Ukendt terminaltype")

    def _decode_input(self, message: dict[str, Any]) -> bytes:
        encoding = str(message.get("encoding") or "utf-8")
        raw = str(message.get("data") or "")
        if encoding == "base64":
            payload = base64.b64decode(raw, validate=True)
        elif encoding == "utf-8":
            payload = raw.encode("utf-8")
        else:
            raise ValueError("Ukendt terminalinputencoding")
        if len(payload) > MAX_INPUT_BYTES:
            raise ValueError("Terminalinput er for stort")
        return payload

    async def _handle_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")
        if message_type == "session_start":
            await self._start_session(message)
            return
        session_id = str(message.get("session_id") or "")
        session = self.sessions.get(session_id)
        if message_type == "ping":
            await self.send({"type": "pong", "session_id": session_id})
            return
        if session is None:
            raise ValueError("Terminalsessionen er ikke aktiv")
        if message_type == "input":
            await session.input(self._decode_input(message))
        elif message_type == "resize":
            cols = int(message.get("cols", 120))
            rows = int(message.get("rows", 32))
            result = session.resize(cols=cols, rows=rows)
            if asyncio.iscoroutine(result):
                await result
        elif message_type == "signal":
            result = session.signal(str(message.get("signal") or ""))
            if asyncio.iscoroutine(result):
                await result
        elif message_type in {"close", "session_stop"}:
            await session.close()
            self.sessions.pop(session_id, None)
        else:
            raise ValueError("Ukendt terminalmeddelelse")

    async def _close_all(self) -> None:
        sessions = list(self.sessions.values())
        self.sessions.clear()
        for session in sessions:
            try:
                await session.close()
            except Exception:
                self.logger.exception("terminal_session_cleanup_failed")

    async def run_forever(self) -> None:
        attempt = 0
        while True:
            try:
                url = self.transport.websocket_url(
                    f"/api/terminal-agent/clients/{self.credential.client_id}/ws"
                )
                async with websockets.connect(
                    url,
                    extra_headers=self.transport.websocket_headers(),
                    ssl=self.ssl_context(),
                    max_size=4 * 1024 * 1024,
                    open_timeout=20,
                    close_timeout=10,
                    ping_interval=20,
                    ping_timeout=20,
                ) as websocket:
                    self.websocket = websocket
                    await asyncio.to_thread(
                        report_status,
                        self.transport,
                        observed_state="online",
                        payload={"standard_terminal": True, "standard_broker_socket": os.path.exists(STANDARD_SOCKET), "root_broker_socket": os.path.exists(ROOT_SOCKET)},
                    )
                    attempt = 0
                    async for raw in websocket:
                        if not isinstance(raw, str) or len(raw) > 4 * 1024 * 1024:
                            raise RuntimeError("Terminal-WebSocket modtog ugyldig meddelelse")
                        message = json.loads(raw)
                        if not isinstance(message, dict):
                            raise RuntimeError("Terminal-WebSocket kræver JSON-objekter")
                        try:
                            await self._handle_message(message)
                        except Exception as exc:
                            session_id = str(message.get("session_id") or "")
                            self.logger.exception("terminal_message_failed", extra={"session_id": session_id})
                            if message.get("type") == "session_start" and session_id:
                                try:
                                    await self.report_event(
                                        session_id,
                                        "broker_rejected",
                                        details={"error": type(exc).__name__},
                                    )
                                except Exception:
                                    self.logger.exception(
                                        "terminal_start_failure_report_failed",
                                        extra={"session_id": session_id},
                                    )
                            await self.send({"type": "error", "session_id": session_id, "error": str(exc)[:500]})
            except KeyboardInterrupt:
                return
            except (ConnectionClosed, OSError, RuntimeError, json.JSONDecodeError):
                self.logger.exception("terminal_connection_failed")
            finally:
                self.websocket = None
                await self._close_all()
            await asyncio.sleep(backoff_seconds(attempt))
            attempt += 1


def main() -> int:
    asyncio.run(TerminalAgent().run_forever())
    return 0
