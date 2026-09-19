from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_action_confirmation_reuses_existing_hot_poll() -> None:
    source = read("frontend/src/pages/clientdetailspage/ClientDetailsPage.jsx")
    assert "const hotPollObservationRef = useRef(" in source
    assert "receivedAt: Date.now()" in source
    assert "observation.receivedAt < startTime" in source
    assert "await getClient(client.id)" not in source
    assert "getChromeStatus(client.id, { fallbackToClient: true })" not in source


def test_request_db_metrics_are_data_minimized() -> None:
    db = read("backend/service1/db.py")
    main = read("backend/service1/main.py")

    assert "statement_count" in db
    assert "checkout_count" in db
    assert "duration_ms" in db
    assert "context._clientflow_db_started_at" in db
    assert '"server_side_pooling": bool(neon_pooler)' in db
    assert '"host": host' not in db
    assert '"topology": database_runtime_topology()' in main
    assert "db_metrics.statement_count" in main
    assert "db_metrics.checkout_count" in main
    assert "db_metrics.duration_ms" in main
