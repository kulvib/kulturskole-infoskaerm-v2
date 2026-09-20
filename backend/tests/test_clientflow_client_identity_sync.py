from __future__ import annotations

from types import SimpleNamespace

from service1.routers.shared_domain import _client_identity_payload


class FakeSession:
    def __init__(self, client):
        self.client = client

    def get(self, model, client_id):
        assert client_id == self.client.id
        return self.client


def test_status_identity_payload_tracks_backend_name_and_locality_without_secrets() -> None:
    client = SimpleNamespace(id=42, name="Viborg4", locality="Kontoret ved Henrik")
    payload = _client_identity_payload(FakeSession(client), 42)
    assert payload == {
        "schema_version": 1,
        "client_id": 42,
        "name": "Viborg4",
        "locality": "Kontoret ved Henrik",
    }
    assert set(payload) == {"schema_version", "client_id", "name", "locality"}
