"""Persistent command queue consumer shared by control domains."""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable

from .logging_utils import configure_logging
from .net import DomainTransport, TransportError, backoff_seconds
from .status import report_status


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


class QueueAgent:
    def __init__(
        self,
        transport: DomainTransport,
        handler: Callable[[CommandContext], dict[str, Any]],
        *,
        poll_seconds: float = 2.0,
        lease_seconds: int = 60,
        status_payload: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.transport = transport
        self.handler = handler
        self.poll_seconds = max(0.2, poll_seconds)
        self.lease_seconds = min(max(lease_seconds, 10), 300)
        self.status_payload = status_payload or (lambda: {})
        self.logger = configure_logging(f"clientflow.{transport.credential.domain.value}")
        self._last_status = 0.0

    def _prefix(self) -> str:
        return self.transport.credential.domain.value.replace("_", "-")

    def _report_status_if_due(self, *, force: bool = False, state: str = "online") -> None:
        now = time.monotonic()
        if not force and now - self._last_status < 30:
            return
        report_status(self.transport, observed_state=state, payload=self.status_payload())
        self._last_status = now

    def _claim(self) -> CommandContext | None:
        client_id = self.transport.credential.client_id
        payload = self.transport.json_request(
            "POST",
            f"/api/{self._prefix()}-agent/clients/{client_id}/commands/claim",
            json_body={"lease_seconds": self.lease_seconds},
        )
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
        while True:
            try:
                self._report_status_if_due()
                context = self._claim()
                if context is None:
                    attempt = 0
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
