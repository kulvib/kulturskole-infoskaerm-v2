from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WebSocketArchitectureContractTests(unittest.TestCase):
    def test_all_websocket_runtime_brokers_use_shared_decoder(self) -> None:
        for relative in (
            "backend/service1/routers/terminal.py",
            "backend/service1/routers/remote_desktop_v2.py",
        ):
            with self.subTest(relative=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("decode_json_message", source)


    def test_livestream_v2_is_http_control_plane_not_websocket_broker(self) -> None:
        source = (ROOT / "backend/service1/routers/livestream_v2.py").read_text(encoding="utf-8")
        self.assertNotIn("@router.websocket(", source)
        self.assertNotIn("decode_json_message", source)

    def test_terminal_has_explicit_agent_and_browser_routes(self) -> None:
        source = (ROOT / "backend/service1/routers/terminal.py").read_text(encoding="utf-8")
        self.assertIn('agent_router = APIRouter(prefix="/terminal-agent"', source)
        self.assertIn('router = APIRouter(prefix="/terminal"', source)
        self.assertIn('@agent_router.websocket("/clients/{client_id}/ws")', source)
        self.assertIn('@router.websocket("/browser/{client_id}/ws")', source)

    def test_remote_desktop_has_explicit_agent_and_browser_limits(self) -> None:
        source = (ROOT / "backend/service1/routers/remote_desktop_v2.py").read_text(encoding="utf-8")
        self.assertIn("MAX_BROWSER_MESSAGE_CHARS = 2_100_000", source)
        self.assertIn("MAX_AGENT_CONTROL_CHARS = 20_000_000", source)
        self.assertIn("MAX_AGENT_FILE_CHARS = 4_500_000", source)
        self.assertIn('@router.websocket("/remote-desktop-agent/clients/{client_id}/control/ws")', source)
        self.assertIn('@router.websocket("/remote-desktop-agent/clients/{client_id}/files/ws")', source)

    def test_update_client_delegates_authorization_and_command_validation(self) -> None:
        source = (ROOT / "backend/service1/routers/clients.py").read_text(encoding="utf-8")
        for helper in (
            "_authorize_client_update_fields",
            "_validate_client_update_privileges",
            "_validate_client_update_command_availability",
        ):
            self.assertIn(f"def {helper}", source)
            self.assertIn(f"    {helper}(", source)
        self.assertNotIn(
            'if "organization_id" in fields: client.organization_id = client_update.organization_id\n    elif "organization_id" in fields:',
            source,
        )


if __name__ == "__main__":
    unittest.main()
