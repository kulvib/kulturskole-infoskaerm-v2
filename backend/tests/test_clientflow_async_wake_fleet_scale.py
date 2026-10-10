"""Offline async wake-up scale contracts; never contact Render or Neon.

A large fleet keeps command wake WebSockets (or HTTPS long polls) open even when
no administrator is connected. Waiting must not park an executor thread per
client. The payload-free signal remains advisory to the durable command queue.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import threading

from service1 import realtime_wakeup as wake


ROOT = Path(__file__).resolve().parents[2]


def test_one_thousand_idle_client_waiters_use_no_blocking_worker_threads():
    async def scenario() -> None:
        domain = "display"
        client_ids = list(range(700_000, 701_000))
        previous = {cid: wake.current_generation(domain, cid) for cid in client_ids}
        before_threads = threading.active_count()
        tasks = [
            asyncio.create_task(wake.wait_for_change_async(domain, cid, previous[cid], 1.0))
            for cid in client_ids
        ]
        await asyncio.sleep(0)
        assert len(tasks) == 1000
        assert all(not task.done() for task in tasks)
        assert threading.active_count() <= before_threads + 1

        target_id = client_ids[531]
        # Simulate after-commit notification from a synchronous request worker.
        publisher = threading.Thread(
            target=wake.notify_command_available, args=(domain, target_id)
        )
        publisher.start()
        publisher.join(timeout=2)
        assert not publisher.is_alive()
        assert await asyncio.wait_for(tasks[531], timeout=2) == previous[target_id] + 1
        assert sum(task.done() for task in tasks) == 1
        for index, task in enumerate(tasks):
            if index != 531:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all((domain, cid) not in wake._ASYNC_WAITERS for cid in client_ids)

    asyncio.run(scenario())


def test_concurrent_listeners_for_one_client_all_receive_wake():
    async def scenario() -> None:
        client_id = 710_001
        after = wake.current_generation("system", client_id)
        tasks = [
            asyncio.create_task(wake.wait_for_change_async("system", client_id, after, 2))
            for _ in range(12)
        ]
        await asyncio.sleep(0)
        assert len(wake._ASYNC_WAITERS[("system", client_id)]) == 12
        generation = wake.notify_command_available("system", client_id)
        assert await asyncio.gather(*tasks) == [generation] * 12
        assert ("system", client_id) not in wake._ASYNC_WAITERS

    asyncio.run(scenario())


def test_async_wait_handles_early_wake_timeout_and_cancel_without_leaks():
    async def scenario() -> None:
        client_id = 710_002
        previous = wake.current_generation("livestream", client_id)
        published = wake.notify_command_available("livestream", client_id)
        # Wake posted before subscription must not be lost.
        assert await wake.wait_for_change_async("livestream", client_id, previous, 2) == published
        assert await wake.wait_for_change_async("livestream", client_id, published, 0.01) == published
        assert ("livestream", client_id) not in wake._ASYNC_WAITERS

        task = asyncio.create_task(wake.wait_for_change_async("livestream", client_id, published, 5))
        await asyncio.sleep(0)
        task.cancel()
        outcome = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(outcome[0], asyncio.CancelledError)
        assert ("livestream", client_id) not in wake._ASYNC_WAITERS

    asyncio.run(scenario())


def test_after_commit_signal_still_respects_rollback_and_scope():
    class FakeSession:
        def __init__(self) -> None:
            self.info: dict = {}

    session = FakeSession()
    after = wake.current_generation("display", 720_001)
    other = wake.current_generation("display", 720_002)
    wake.queue_wakeup_after_commit(session, domain="display", client_id=720_001)
    assert wake.current_generation("display", 720_001) == after
    wake.discard_session_wakeups(session)
    wake.publish_session_wakeups(session)
    assert wake.current_generation("display", 720_001) == after
    wake.queue_wakeup_after_commit(session, domain="display", client_id=720_001)
    wake.publish_session_wakeups(session)
    assert wake.current_generation("display", 720_001) == after + 1
    assert wake.current_generation("display", 720_002) == other


def test_all_agent_websocket_and_http_wait_routes_are_nonblocking():
    shared = (ROOT / "backend/service1/routers/shared_domain.py").read_text(encoding="utf-8")
    livestream = (ROOT / "backend/service1/routers/livestream_v2.py").read_text(encoding="utf-8")
    assert "await wait_for_change_async(" in shared
    assert "async def display_wait(" in shared
    assert "async def system_wait(" in shared
    assert "async def _wake_wait(" in shared
    assert "async def livestream_command_wait(" in livestream
    assert "await wait_for_wake_change_async(" in livestream
    assert "asyncio.to_thread(" not in shared
    assert "asyncio.to_thread(" not in livestream
