from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from service1.http_ws_relay import close_relay, create_relay, get_relay, require_relay_scope


def test_https_relay_reuses_websocket_shape_with_scope_and_bounded_lifecycle() -> None:
    async def scenario() -> None:
        async def handler(socket) -> None:
            await socket.accept()
            raw = await socket.receive_text()
            payload = json.loads(raw)
            await socket.send_text(json.dumps({"type": "echo", "value": payload["value"]}))

        relay = await create_relay(
            handler,
            headers={"authorization": "Bearer test"},
            scope={"kind": "test", "client_id": 7},
        )
        require_relay_scope(relay, kind="test", client_id=7)
        with pytest.raises(HTTPException):
            require_relay_scope(relay, kind="test", client_id=8)

        await relay.push_from_http(json.dumps({"value": "ok"}))
        messages = [json.loads(value) for value in await relay.poll_to_http(2)]
        assert messages[0] == {"type": "echo", "value": "ok"}

        # The handler has completed, so the relay publishes its bounded close
        # marker rather than leaving a hanging long-poll resource behind. It may
        # be drained in the same HTTP poll as the final application message.
        if not any(value.get("type") == "relay_closed" for value in messages):
            messages.extend(json.loads(value) for value in await relay.poll_to_http(2))
        assert any(value.get("type") == "relay_closed" for value in messages)
        await close_relay(relay.relay_id, reason="test_done")

    asyncio.run(scenario())


def test_https_relay_lookup_fails_closed_after_explicit_close() -> None:
    async def scenario() -> None:
        async def handler(socket) -> None:
            await socket.accept()
            await socket.receive_text()

        relay = await create_relay(handler, scope={"kind": "test", "client_id": 8})
        assert await get_relay(relay.relay_id) is relay
        await close_relay(relay.relay_id, reason="test_close")
        with pytest.raises(HTTPException) as exc:
            await get_relay(relay.relay_id)
        assert exc.value.status_code == 404

    asyncio.run(scenario())
