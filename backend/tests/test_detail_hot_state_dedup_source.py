from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENTS = (ROOT / "backend/service1/routers/clients.py").read_text(encoding="utf-8")
PRESENCE = (ROOT / "backend/service1/client_presence.py").read_text(encoding="utf-8")


def test_detail_hot_read_joins_client_and_presence_evidence_once() -> None:
    assert "def load_client_with_presence_rows(" in PRESENCE
    helper = PRESENCE.split("def load_client_with_presence_rows(", 1)[1].split("def _load_client_presence_batch(", 1)[0]
    assert "select(Client, ClientDomainStatus, ClientDomainCredential)" in helper
    assert "load_only(" in helper
    assert "ClientDomainCredential.revoked_at" in helper
    assert "secret_hash" not in helper
    assert ".where(Client.id == int(client_id))" in helper

    chrome = CLIENTS.split('@router.get("/clients/{id}/chrome-status")', 1)[1].split('@router.put("/clients/{id}/chrome-status")', 1)[0]
    assert "load_client_with_presence_rows(session, id)" in chrome
    assert "session.get(Client, id)" not in chrome
    assert "load_client_presences_with_status_rows(session, [client])" not in chrome


def test_full_detail_read_reuses_bounded_batch_projection() -> None:
    detail = CLIENTS.split('@router.get("/clients/{id}/", response_model=ClientRead)', 1)[1].split('@router.get("/clients/{id}/local-management"', 1)[0]
    assert "load_client_with_presence_rows(session, id)" in detail
    assert "_prepare_single_client_read_from_loaded_presence" in detail

    helper = CLIENTS.split("def _prepare_single_client_read_from_loaded_presence(", 1)[1].split("def _prepare_full_client_read(", 1)[0]
    assert "display_read_projections(" in helper
    assert "load_latest_system_projection_commands(" in helper
