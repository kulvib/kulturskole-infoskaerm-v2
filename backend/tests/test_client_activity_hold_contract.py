from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_shared_activity_model_is_narrow_and_domain_neutral():
    model = read("service1/client_activity_models.py")
    service = read("service1/client_activity.py")
    assert '__tablename__ = "client_activity_lease"' in model
    assert "terminal" in model
    assert "remote_desktop" in model
    assert "livestream_v2" not in service
    assert "request_start" not in service
    assert "request_stop" not in service
    assert 'ACTIVITY_DOMAINS = frozenset({"terminal", "remote_desktop"})' in service
    assert 'CLIENT_ACTIVITY_LEASE_SECONDS", "60"' in service
    assert 'CLIENT_ACTIVITY_RENEW_SECONDS", "15"' in service
    assert 'CLIENT_ACTIVITY_RETENTION_SECONDS", "3600"' in service
    assert "def prune_old_activity_leases(" in service
    assert "def active_livestream_activity_client_ids(" in service


def test_terminal_and_remote_desktop_publish_only_their_own_browser_presence():
    terminal = read("service1/routers/terminal.py")
    remote = read("service1/routers/remote_desktop_v2.py")
    assert "maintain_activity_lease" in terminal
    assert 'domain="terminal"' in terminal
    assert "end_activity_lease" in terminal
    assert "maintain_activity_lease" in remote
    assert 'domain="remote_desktop"' in remote
    assert "end_activity_lease" in remote
    assert "request_start" not in terminal
    assert "request_start" not in remote


def test_any_authenticated_client_activity_can_start_or_hold_livestream():
    source = read("service1/livestream_v2.py")
    start = source.index("def reconcile_viewer_lifecycle(")
    end = source.index("def reconcile_all_viewer_lifecycles(", start)
    block = source[start:end]
    assert "active_livestream_activity_count(session, client_id)" in block
    assert "if active_viewers > 0 or active_client_activity > 0:" in block
    assert 'source="viewer_reconcile" if active_viewers > 0 else "client_activity_reconcile"' in block
    assert "if generation is None:" in block
    assert "request_start(" in block
    assert "last_livestream_activity_ended_at(session, client_id)" in block


def test_activity_only_clients_are_sweeper_candidates_for_start():
    source = read("service1/livestream_v2.py")
    start = source.index("def reconcile_all_viewer_lifecycles(")
    end = source.index("def _sweeper_loop(", start)
    block = source[start:end]
    assert "candidate_ids.update(active_livestream_activity_client_ids(session))" in block


def test_recovery_and_stale_media_respect_terminal_or_rd_activity():
    source = read("service1/livestream_v2.py")
    assert "activity_active = active_livestream_activity_count(session, client_id) > 0" in source
    assert '"client_activity_returned_during_recovery"' in source
    stale_start = source.index("def maybe_recover_stale_media(")
    stale_end = source.index("def reconcile_viewer_lifecycle(", stale_start)
    stale = source[stale_start:stale_end]
    assert "active_livestream_activity_count(session, client_id) == 0" in stale


def test_last_activity_end_starts_the_same_30_second_stop_grace():
    source = read("service1/livestream_v2.py")
    start = source.index("def reconcile_viewer_lifecycle(")
    end = source.index("def reconcile_all_viewer_lifecycles(", start)
    block = source[start:end]
    assert "last_viewer_ended" in block
    assert "last_activity_ended" in block
    assert "max(ended_candidates)" in block
    assert "VIEWER_STOP_GRACE_SECONDS" in block
    assert 'request_stop(session, client_id, source="client_activity_grace_expired")' in block


def test_step_47a_migration_and_schema_contract_are_reviewed():
    migration = read("migrations/versions/20260818_47a_client_activity_lease.py")
    contract = read("scripts/display_schema_contract.py")
    runner = read("scripts/run_migrations.py")
    assert 'revision = "20260818_47a_client_activity"' in migration
    assert 'down_revision = "20260817_46a_remote_desktop_v2"' in migration
    assert '"client_activity_lease"' in migration
    assert 'EXPECTED_HEAD_REVISION = "20260818_47a_client_activity"' in contract
    assert 'REVIEWED_CLIENT_ACTIVITY_REVISION = "20260818_47a_client_activity"' in runner
    assert "_without_client_activity_schema" in runner
