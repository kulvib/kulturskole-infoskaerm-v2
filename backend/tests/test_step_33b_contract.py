from __future__ import annotations

import ast
from pathlib import Path
import unittest

from service1.websocket_auth import (
    BROWSER_WS_SUBPROTOCOL,
    extract_agent_ws_token,
    extract_browser_ws_ticket,
    extract_browser_ws_token,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "backend" / "service1"


class FakeWebSocket:
    def __init__(
        self,
        *,
        query_token: str | None = None,
        cookie_token: str | None = None,
        bearer_token: str | None = None,
        protocols: str | None = None,
    ):
        self.query_params = {"token": query_token} if query_token else {}
        self.cookies = {"access_token": cookie_token} if cookie_token else {}
        self.headers = {}
        if bearer_token:
            self.headers["authorization"] = f"Bearer {bearer_token}"
        if protocols:
            self.headers["sec-websocket-protocol"] = protocols


class Step33BContractTests(unittest.TestCase):
    def test_backend_runtime_has_no_print_or_traceback_print_exc(self) -> None:
        violations: list[str] = []
        for path in SERVICE_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: print")
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "print_exc"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "traceback"
                ):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: traceback.print_exc")
        self.assertEqual(violations, [])

    def test_browser_websocket_auth_uses_ticket_or_cookie_and_ignores_query(self) -> None:
        ticket = "A" * 43
        ticket_ws = FakeWebSocket(protocols=f"{BROWSER_WS_SUBPROTOCOL}, {ticket}")
        self.assertEqual(extract_browser_ws_ticket(ticket_ws), ticket)

        cookie_ws = FakeWebSocket(
            query_token="old-browser-query-token",
            cookie_token="fresh-cookie-token",
        )
        self.assertEqual(extract_browser_ws_token(cookie_ws), "fresh-cookie-token")

        query_only = FakeWebSocket(query_token="browser-query-token")
        self.assertIsNone(extract_browser_ws_token(query_only))
        self.assertIsNone(extract_browser_ws_ticket(query_only))

    def test_agent_websocket_auth_keeps_query_token_contract(self) -> None:
        ws = FakeWebSocket(query_token="clientflow-agent-token", cookie_token="cookie-token")
        self.assertEqual(extract_agent_ws_token(ws), "clientflow-agent-token")

    def test_browser_websocket_urls_do_not_include_access_token(self) -> None:
        api_source = (REPO_ROOT / "frontend/src/api/api.js").read_text(encoding="utf-8")
        remote_source = (
            REPO_ROOT / "frontend/src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx"
        ).read_text(encoding="utf-8")

        self.assertNotIn('params.set("token"', api_source)
        self.assertNotIn("getAuthToken", remote_source)
        self.assertIn("getRemoteDesktopBrowserWsUrl", remote_source)

    def test_browser_and_agent_endpoints_use_separate_auth_helpers(self) -> None:
        terminal_source = (SERVICE_ROOT / "routers/terminal.py").read_text(encoding="utf-8")
        remote_source = (SERVICE_ROOT / "routers/remote_desktop_v2.py").read_text(encoding="utf-8")

        self.assertIn("authenticate_browser_websocket", terminal_source)
        self.assertIn("extract_agent_ws_token", terminal_source)
        self.assertIn("await websocket.accept(subprotocol=selected_subprotocol)", terminal_source)

        self.assertIn("authenticate_browser_websocket", remote_source)
        self.assertIn("_extract_agent_bearer", remote_source)
        self.assertIn("verify_remote_desktop_agent_token", remote_source)
        self.assertIn("await websocket.accept(subprotocol=selected_subprotocol)", remote_source)

        for source in (terminal_source, remote_source):
            self.assertNotIn("browser=True", source)
            self.assertNotIn("browser=False", source)

    def test_livestream_contract_is_three_minutes_and_two_segments(self) -> None:
        frontend_source = (
            REPO_ROOT / "frontend/src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx"
        ).read_text(encoding="utf-8")
        backend_source = (SERVICE_ROOT / "routers/livestream.py").read_text(encoding="utf-8")
        render_source = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")

        self.assertIn("HIDDEN_INACTIVITY_STOP_MS = 3 * 60 * 1000", frontend_source)
        self.assertIn("Siden har ikke været besøgt i 3 min.", frontend_source)
        self.assertIn("HLS_INITIAL_MANIFEST_SEGMENTS = 2", frontend_source)
        self.assertIn('HLS_VIEWER_HEARTBEAT_TIMEOUT_SECONDS", "180"', backend_source)
        self.assertIn("HLS_VIEWER_HEARTBEAT_TIMEOUT_SECONDS", render_source)
        self.assertIn('value: "180"', render_source)

    def test_websocket_and_hls_errors_are_neutral(self) -> None:
        terminal_source = (SERVICE_ROOT / "routers/terminal.py").read_text(encoding="utf-8")
        remote_source = (SERVICE_ROOT / "routers/remote_desktop_v2.py").read_text(encoding="utf-8")
        livestream_source = (SERVICE_ROOT / "routers/livestream.py").read_text(encoding="utf-8")

        self.assertNotIn('"message": str(exc)', terminal_source)
        self.assertNotIn("repr(exc)", terminal_source)
        self.assertNotIn("repr(exc)", remote_source)
        self.assertNotIn("traceback.format_exc", remote_source)
        self.assertNotIn("reset failed:", livestream_source)
        self.assertIn('"message": "reset failed"', livestream_source)


if __name__ == "__main__":
    unittest.main()
