"""System command agent. It can call only the fixed-function local system broker."""
from __future__ import annotations

import os
from typing import Any

from .command_agent import CommandContext, CommandRejected, QueueAgent
from .config import DomainCredential
from .constants import Domain
from .net import DomainTransport
from .release_download import ReleaseDownloadError, download_release_bundle
from .unix_rpc import RpcError, call

SYSTEM_SOCKET = os.getenv("CLIENTFLOW_SYSTEM_SOCKET", "/run/clientflow/system.sock")


def build_handler(transport: DomainTransport):
    def handle(context: CommandContext) -> dict[str, Any]:
        payload = dict(context.payload)
        if context.command_type == "update_clientflow":
            try:
                bundle = download_release_bundle(transport, payload)
            except ReleaseDownloadError as exc:
                raise CommandRejected("release_download_failed", str(exc), retryable=True) from exc
            if bundle.name != f"{payload['release_id']}.tar":
                raise CommandRejected("release_download_failed", "Releasefilen har uventet navn", retryable=False)
            payload = {"release_id": payload["release_id"]}
        try:
            return call(
                SYSTEM_SOCKET,
                {
                    "action": context.command_type,
                    "client_id": context.client_id,
                    "command_id": context.command_id,
                    "schema_version": context.schema_version,
                    "payload": payload,
                },
                timeout=7250 if context.command_type == "update_os" else 1850,
            )
        except RpcError as exc:
            message = str(exc)
            in_doubt = "system_command_in_doubt" in message or "system_command_journal" in message
            retryable = (
                not in_doubt
                and context.command_type in {"update_os", "update_clientflow", "activate_release", "rollback_release"}
            )
            code = "system_command_in_doubt" if in_doubt else "system_broker_error"
            raise CommandRejected(code, message, retryable=retryable) from exc
    return handle


def main() -> int:
    credential = DomainCredential.load(Domain.SYSTEM)
    transport = DomainTransport(credential)
    QueueAgent(
        transport,
        build_handler(transport),
        lease_seconds=300,
        status_payload=lambda: {"broker_socket": os.path.exists(SYSTEM_SOCKET)},
    ).run_forever()
    return 0
