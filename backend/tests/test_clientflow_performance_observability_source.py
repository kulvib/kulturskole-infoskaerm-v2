from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "backend/service1/main.py").read_text(encoding="utf-8")
CLIENTS = (ROOT / "backend/service1/routers/clients.py").read_text(encoding="utf-8")
PRESENCE = (ROOT / "backend/service1/client_presence.py").read_text(encoding="utf-8")


def test_client_api_exposes_dataminimized_server_timing():
    assert 'request.url.path.startswith("/api/clients")' in MAIN
    assert 'Server-Timing' in MAIN
    assert 'app;dur=' in MAIN
    assert 'perf_counter()' in MAIN


def test_presence_loader_joins_credentials_in_one_roundtrip():
    block = PRESENCE.split("def _load_client_presence_batch", 1)[1].split("def load_client_presences", 1)[0]
    assert "select(ClientDomainStatus, ClientDomainCredential)" in block
    assert ".join(" in block
    assert "credential_ids" not in block
    assert "select(ClientDomainCredential).where" not in block


def test_chrome_status_transports_already_evaluated_canonical_presence():
    block = CLIENTS.split('@router.get("/clients/{id}/chrome-status")', 1)[1].split('@router.put("/clients/{id}/chrome-status")', 1)[0]
    assert '"presence": presence.public_dict()' in block
