from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding="utf-8")


def test_manual_stop_route_and_service_share_explicit_contract():
    service = read("service1/livestream_v2.py")
    router = read("service1/routers/livestream_v2.py")

    stop_start = service.index("def request_stop(")
    stop_end = service.index("def _recover_expired_leases(", stop_start)
    stop_block = service[stop_start:stop_end]

    assert "explicit: bool = False" in stop_block
    assert 'client.livestream_stop_reason = f"explicit_stop:{stop_reason}"[:500]' in stop_block
    assert "elif not explicit_stop_latched(session, client_id):" in stop_block
    assert "explicit=True" in router


def test_explicit_stop_latch_blocks_every_auto_start_path():
    service = read("service1/livestream_v2.py")
    router = read("service1/routers/livestream_v2.py")

    heartbeat_start = service.index("def viewer_heartbeat(")
    heartbeat_end = service.index("def viewer_leave(", heartbeat_start)
    heartbeat = service[heartbeat_start:heartbeat_end]
    assert "not explicit_stop_latched(session, client_id)" in heartbeat

    recovery_start = service.index("def reconcile_stopping_generation_from_agent_status(")
    recovery_end = service.index("def update_agent_status(", recovery_start)
    recovery = service[recovery_start:recovery_end]
    assert "not explicit_stop_latched(session, client_id)" in recovery

    lifecycle_start = service.index("def reconcile_viewer_lifecycle(")
    lifecycle_end = service.index("def reconcile_all_viewer_lifecycles(", lifecycle_start)
    lifecycle = service[lifecycle_start:lifecycle_end]
    assert "if explicit_stop_latched(session, client_id):" in lifecycle

    ack_start = router.index("def agent_generation_stopped(")
    ack_end = router.index("@router.put", ack_start)
    ack = router[ack_start:ack_end]
    assert "not explicit_stop_latched(session, client_id)" in ack


def test_real_manual_generation_creation_still_clears_the_latch():
    service = read("service1/livestream_v2.py")
    start = service.index("def _new_generation(")
    end = service.index("def request_start(", start)
    block = service[start:end]

    assert "client.livestream_stop_reason = None" in block
