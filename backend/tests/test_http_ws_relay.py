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


def test_https_relay_explicit_close_has_bounded_drain_grace() -> None:
    async def scenario() -> None:
        async def handler(socket) -> None:
            await socket.accept()
            await socket.receive_text()

        relay = await create_relay(handler, scope={"kind": "test", "client_id": 8})
        assert await get_relay(relay.relay_id) is relay
        await close_relay(relay.relay_id, reason="test_close")
        drained = await get_relay(relay.relay_id)
        assert drained.closed is True
        messages = [json.loads(value) for value in await drained.poll_to_http(1)]
        assert any(value.get("type") == "relay_closed" for value in messages)

    asyncio.run(scenario())


def test_https_relay_global_byte_budget_fails_closed(monkeypatch) -> None:
    import service1.http_ws_relay as relay_module

    async def scenario() -> None:
        async def handler(socket) -> None:
            await socket.accept()
            await asyncio.Event().wait()

        monkeypatch.setattr(relay_module, "MAX_TOTAL_QUEUE_BYTES", 12)
        relay = await create_relay(
            handler, scope={"kind": "budget-test", "client_id": 9, "user_id": 1}
        )
        relay._put_outgoing("12345678")
        with pytest.raises(RuntimeError, match="global byte-backpressure"):
            relay._put_outgoing("12345678")
        await close_relay(relay.relay_id, reason="budget_test_done")

    asyncio.run(scenario())
