from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from starlette.requests import Request

from service1 import auth
from service1.models import Client, ClientRead, ClientUpdate
from service1.routers.clients import CLIENT_SELF_UPDATE_FIELDS


RUNTIME_FIELDS = {
    "client_version_patch",
    "client_version_updated_at",
    "ubuntu_update_status",
    "ubuntu_update_step",
    "ubuntu_update_message",
    "ubuntu_update_error",
    "ubuntu_update_started_at",
    "ubuntu_update_updated_at",
    "ubuntu_update_finished_at",
    "ubuntu_update_progress",
    "ubuntu_update_package_count",
    "ubuntu_update_reboot_required",
    "client_update_target_version",
    "client_update_target_release_sequence",
    "client_update_deployment_sequence",
    "client_update_applied_deployment_sequence",
    "client_update_allow_downgrade",
    "client_update_reason",
}

LIVESTREAM_BACKEND_STATE_FIELDS = {
    
    
    "livestream_desired_state",
    "livestream_stop_reason",
    
}

LEGACY_CLIENTFLOW_UPDATE_FIELDS = {
    "client_update_status",
    "client_update_message",
    "client_update_requested_at",
    "client_update_started_at",
    "client_update_finished_at",
    "client_update_error",
    "client_update_target_version",
    "client_update_target_release_sequence",
    "client_update_deployment_sequence",
    "client_update_applied_deployment_sequence",
    "client_update_allow_downgrade",
    "client_update_reason",
}

BACKEND_AUTHORITATIVE_UPDATE_TARGET_FIELDS = {
    "client_update_target_version",
    "client_update_deployment_sequence",
}


class _Session:
    def __init__(self, client):
        self.client = client

    def get(self, model, key):
        self.last_get = (model, key)
        return self.client


class ClientRuntimeContractTests(unittest.TestCase):
    def test_runtime_fields_are_present_in_database_and_api_models(self) -> None:
        for model in (Client, ClientRead, ClientUpdate):
            self.assertTrue(RUNTIME_FIELDS.issubset(model.model_fields))
        self.assertTrue(LEGACY_CLIENTFLOW_UPDATE_FIELDS.isdisjoint(CLIENT_SELF_UPDATE_FIELDS))
        self.assertTrue(BACKEND_AUTHORITATIVE_UPDATE_TARGET_FIELDS.isdisjoint(CLIENT_SELF_UPDATE_FIELDS))
        for model in (Client, ClientRead):
            self.assertTrue(LIVESTREAM_BACKEND_STATE_FIELDS.issubset(model.model_fields))
        self.assertTrue(LIVESTREAM_BACKEND_STATE_FIELDS.isdisjoint(ClientUpdate.model_fields))
        self.assertTrue(LIVESTREAM_BACKEND_STATE_FIELDS.isdisjoint(CLIENT_SELF_UPDATE_FIELDS))
        self.assertNotIn("client_update_reason", CLIENT_SELF_UPDATE_FIELDS)
        self.assertNotIn("client_update_allow_downgrade", CLIENT_SELF_UPDATE_FIELDS)

    def test_client_update_preserves_detailed_ubuntu_payload(self) -> None:
        payload = {
            "ubuntu_update_status": "installing",
            "ubuntu_update_step": "os_update_installing",
            "ubuntu_update_message": "Installerer pakker",
            "ubuntu_update_progress": 64,
            "ubuntu_update_package_count": 12,
            "ubuntu_update_reboot_required": True,
            "client_version_patch": "v1.1.7_runtime_contract",
        }
        parsed = ClientUpdate(**payload).model_dump(exclude_unset=True)
        self.assertEqual(parsed, payload)

    def test_client_token_response_exposes_authoritative_expiry(self) -> None:
        client = SimpleNamespace(
            id=42,
            name="Testskærm",
            status="approved",
            organization_id=7,
            client_secret_hash="hash",
            client_secret_revoked_at=None,
            deleted_at=None,
            client_token_version=0,
        )
        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/auth/client-token",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
        })
        with patch.object(auth, "enforce_request_rate_limit"), patch.object(
            auth, "verify_password", return_value=True
        ), patch.object(auth, "create_access_token", return_value="token"):
            result = auth.login_for_client_token(
                request=request,
                data=auth.ClientTokenRequest(client_id=42, client_secret="secret"),
                session=_Session(client),
            )
        self.assertEqual(result["expires_in"], auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


if __name__ == "__main__":
    unittest.main()
