"""Persistent command queue consumer shared by control domains."""
from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json
import threading
import time
from typing import Any, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from .constants import SHARED_DOMAIN_COMMAND_POLL_SECONDS, SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS
from .logging_utils import configure_logging
from .net import DomainTransport, TransportError, backoff_seconds
from .status import build_status_body, report_status


@dataclass(frozen=True, slots=True)
class CommandContext:
    command_id: str
    client_id: int
    command_type: str
    payload: dict[str, Any]
    schema_version: int
    claim_token: str


class CommandRejected(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class LeaseKeeper:
    def __init__(self, transport: DomainTransport, context: CommandContext, *, lease_seconds: int) -> None:
        self.transport = transport
        self.context = context
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._failed: Exception | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"lease-{context.command_id}")

    def __enter__(self) -> "LeaseKeeper":
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.lease_seconds / 2))
        if exc is None and self._failed is not None:
            raise self._failed

    def _run(self) -> None:
        interval = max(5.0, self.lease_seconds / 3)
        while not self._stop.wait(interval):
            try:
                domain = self.transport.credential.domain.value.replace("_", "-")
                client_id = self.transport.credential.client_id
                self.transport.json_request(
                    "POST",
                    f"/api/{domain}-agent/clients/{client_id}/commands/{self.context.command_id}/renew",
                    json_body={
                        "claim_token": self.context.claim_token,
                        "lease_seconds": self.lease_seconds,
                    },
                )
            except Exception as exc:  # The command must not be acknowledged after lease loss.
                self._failed = exc
                self._stop.set()
                return




class CommandWakeChannel:
    """Best-effort WSS wake channel with HTTPS long-poll fallback.

    The channel never transports command payloads. A wake only causes the
    existing durable claim endpoint to run, so correctness remains database-
    authoritative even if every realtime signal is lost.
    """

    def __init__(self, transport: DomainTransport, logger) -> None:
        self.transport = transport
        self.logger = logger
        self.event = threading.Event()
        self.stop = threading.Event()
        self.generation = 0
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"wake-{transport.credential.domain.value}")

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.event.set()

    def wait(self, timeout: float) -> bool:
        signalled = self.event.wait(timeout)
        if signalled:
            self.event.clear()
        return signalled

    def _wake(self, generation: int) -> None:
        self.generation = max(self.generation, int(generation))
        self.event.set()

    async def _websocket_once_async(self) -> None:
        domain = self.transport.credential.domain.value.replace("_", "-")
        client_id = self.transport.credential.client_id
        path = f"/api/{domain}-agent/clients/{client_id}/commands/wake/ws"
        url = self.transport.websocket_url(path)
        ssl_context = self.transport._ssl_context if url.startswith("wss:") else None
        async with websockets.connect(
            url,
            extra_headers=self.transport.websocket_headers(),
            ssl=ssl_context,
            open_timeout=15,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=64 * 1024,
        ) as websocket:
            while not self.stop.is_set():
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=55)
                except asyncio.TimeoutError:
                    continue
                if not isinstance(raw, str):
                    continue
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    continue
                generation = int(payload.get("generation") or self.generation)
                self.generation = max(self.generation, generation)
                if payload.get("type") == "command_available":
                    self._wake(generation)

    def _websocket_once(self) -> None:
        asyncio.run(self._websocket_once_async())

    def _long_poll_once(self) -> None:
        domain = self.transport.credential.domain.value.replace("_", "-")
        client_id = self.transport.credential.client_id
        payload = self.transport.json_request(
            "GET",
            f"/api/{domain}-agent/clients/{client_id}/commands/wait?after={self.generation}&timeout_seconds=25",
            timeout=35,
        )
        generation = int(payload.get("generation") or self.generation)
        if payload.get("changed") is True or generation > self.generation:
            self._wake(generation)
        else:
            self.generation = max(self.generation, generation)

    def _run(self) -> None:
        websocket_failures = 0
        while not self.stop.is_set():
            try:
                self._websocket_once()
                websocket_failures = 0
                continue
            except (ConnectionClosed, OSError, RuntimeError, TimeoutError, json.JSONDecodeError, TypeError) as exc:
                websocket_failures += 1
                if websocket_failures == 1:
                    self.logger.info("command_wake_websocket_fallback", extra={"event": str(exc)[:160]})
            # HTTPS long-poll uses normal outbound TCP/443 and proxy handling,
            # preserving operation on networks that block WebSocket upgrades.
            try:
                self._long_poll_once()
            except Exception:
                if self.stop.wait(backoff_seconds(min(websocket_failures, 5))):
                    return

class QueueAgent:
    def __init__(
        self,
        transport: DomainTransport,
        handler: Callable[[CommandContext], dict[str, Any]],
        *,
        poll_seconds: float = SHARED_DOMAIN_COMMAND_POLL_SECONDS,
        lease_seconds: int = 60,
        status_payload: Callable[[], dict[str, Any]] | None = None,
        report_status_after_command: bool = False,
        piggyback_status_on_claim: bool = False,
    ) -> None:
        self.transport = transport
        self.handler = handler
        self.poll_seconds = max(0.2, poll_seconds)
        self.lease_seconds = min(max(lease_seconds, 10), 300)
        self.status_payload = status_payload or (lambda: {})
        self.report_status_after_command = bool(report_status_after_command)
        self.piggyback_status_on_claim = bool(piggyback_status_on_claim)
        self._last_claim_status_reported = False
        self.logger = configure_logging(f"clientflow.{transport.credential.domain.value}")
        self._last_status = 0.0
        self._wake_channel = (
            CommandWakeChannel(transport, self.logger)
            if transport.credential.domain.value in {"display", "system"}
            else None
        )

    def _prefix(self) -> str:
        return self.transport.credential.domain.value.replace("_", "-")

    def _status_due(self, *, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and now - self._last_status < SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS:
            return False
        return True

    def _report_status_if_due(self, *, force: bool = False, state: str = "online") -> None:
        if not self._status_due(force=force):
            return
        report_status(self.transport, observed_state=state, payload=self.status_payload())
        self._last_status = time.monotonic()

    def _claim(self, *, status_report: dict[str, Any] | None = None) -> CommandContext | None:
        client_id = self.transport.credential.client_id
        body: dict[str, Any] = {"lease_seconds": self.lease_seconds}
        if status_report is not None:
            body["status_report"] = status_report
        payload = self.transport.json_request(
            "POST",
            f"/api/{self._prefix()}-agent/clients/{client_id}/commands/claim",
            json_body=body,
        )
        self._last_claim_status_reported = payload.get("status_reported") is True
        claimed = payload.get("claimed")
        if claimed is None:
            return None
        if not isinstance(claimed, dict) or not isinstance(claimed.get("command"), dict):
            raise TransportError("Command claim-respons er ugyldig", retryable=False)
        command = claimed["command"]
        context = CommandContext(
            command_id=str(command["id"]),
            client_id=int(command["client_id"]),
            command_type=str(command["command_type"]),
            payload=dict(command.get("payload") or {}),
            schema_version=int(command["schema_version"]),
            claim_token=str(claimed["claim_token"]),
        )
        if context.client_id != self.transport.credential.client_id:
            raise TransportError("Command er bundet til en anden klient", retryable=False)
        if context.schema_version != 1:
            raise TransportError("Command schema_version understøttes ikke", retryable=False)
        return context

    def _complete(self, context: CommandContext, result: dict[str, Any]) -> None:
        client_id = self.transport.credential.client_id
        self.transport.json_request(
            "POST",
            f"/api/{self._prefix()}-agent/clients/{client_id}/commands/{context.command_id}/complete",
            json_body={"claim_token": context.claim_token, "result": result},
        )

    def _fail(self, context: CommandContext, exc: Exception) -> None:
        if isinstance(exc, CommandRejected):
            code = exc.code
            retryable = exc.retryable
        elif isinstance(exc, TransportError):
            code = "transport_error"
            retryable = exc.retryable
        else:
            code = "handler_error"
            retryable = False
        client_id = self.transport.credential.client_id
        self.transport.json_request(
            "POST",
            f"/api/{self._prefix()}-agent/clients/{client_id}/commands/{context.command_id}/fail",
            json_body={
                "claim_token": context.claim_token,
                "error_code": code,
                "error_message": str(exc)[:2000],
                "retryable": retryable,
            },
        )

    def run_forever(self) -> None:
        attempt = 0
        if self._wake_channel is not None:
            self._wake_channel.start()
        while True:
            try:
                piggybacked_status: dict[str, Any] | None = None
                if self.piggyback_status_on_claim and self._status_due():
                    piggybacked_status = build_status_body(
                        observed_state="online",
                        payload=self.status_payload(),
                    )
                elif not self.piggyback_status_on_claim:
                    self._report_status_if_due()

                context = self._claim(status_report=piggybacked_status)
                if piggybacked_status is not None:
                    if self._last_claim_status_reported:
                        # The backend applies status and claim in one transaction. Only
                        # advance the cadence when the backend explicitly acknowledges it.
                        self._last_status = time.monotonic()
                    else:
                        # Rolling-upgrade compatibility: older backends may ignore the
                        # optional field. Preserve liveness with the historical PUT.
                        self._report_status_if_due(force=True)
                if context is None:
                    attempt = 0
                    if self._wake_channel is not None:
                        # Keep the historical status/liveness cadence without
                        # turning every heartbeat into a durable queue claim.
                        # Wakes claim immediately; otherwise a DB reconciliation
                        # claim runs at most once per minute.
                        reconciliation_deadline = time.monotonic() + max(60.0, self.poll_seconds)
                        while True:
                            remaining = reconciliation_deadline - time.monotonic()
                            if remaining <= 0:
                                break
                            if self._wake_channel.wait(
                                min(SHARED_DOMAIN_STATUS_REPORT_INTERVAL_SECONDS, remaining)
                            ):
                                break
                            self._report_status_if_due()
                    else:
                        time.sleep(self.poll_seconds)
                    continue
                self.logger.info(
                    "command_claimed",
                    extra={"command_id": context.command_id, "event": context.command_type},
                )
                try:
                    with LeaseKeeper(self.transport, context, lease_seconds=self.lease_seconds):
                        result = self.handler(context)
                    self._complete(context, result)
                    if self.report_status_after_command:
                        self._report_status_if_due(force=True)
                    self.logger.info("command_completed", extra={"command_id": context.command_id})
                except Exception as exc:
                    self.logger.exception("command_failed", extra={"command_id": context.command_id})
                    self._fail(context, exc)
                attempt = 0
            except KeyboardInterrupt:
                return
            except Exception:
                self.logger.exception("agent_loop_failed")
                try:
                    self._report_status_if_due(force=True, state="degraded")
                except Exception:
                    pass
                time.sleep(backoff_seconds(attempt))
                attempt += 1
