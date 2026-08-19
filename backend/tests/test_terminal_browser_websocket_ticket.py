from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from service1.models import User
from service1.terminal_websocket_auth import (
    TERMINAL_BROWSER_WS_CAPABILITIES,
    TERMINAL_BROWSER_WS_SUBPROTOCOL,
    TerminalBrowserWsTicketStoreFull,
    _clear_terminal_browser_ws_ticket_store_for_tests,
    authenticate_terminal_browser_websocket_with_context,
    consume_terminal_browser_ws_ticket,
    extract_terminal_browser_ws_ticket,
    issue_terminal_browser_ws_ticket,
)
from service1.websocket_auth import (
    _clear_browser_ws_ticket_store_for_tests,
    consume_browser_ws_ticket,
    issue_browser_ws_ticket,
)


class FakeWebSocket:
    def __init__(self, protocols: str = "", cookie_token: str = ""):
        self.headers = {"sec-websocket-protocol": protocols} if protocols else {}
        self.cookies = {"access_token": cookie_token} if cookie_token else {}
        self.query_params = {}


class TerminalBrowserWebSocketTicketTests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_terminal_browser_ws_ticket_store_for_tests()
        _clear_browser_ws_ticket_store_for_tests()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            user = User(
                username="superadmin",
                email="superadmin@example.test",
                hashed_password="not-used",
                role="superadmin",
                is_active=True,
                must_change_password=False,
                token_version=7,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            self.user_id = int(user.id)

    def tearDown(self) -> None:
        _clear_terminal_browser_ws_ticket_store_for_tests()
        _clear_browser_ws_ticket_store_for_tests()
        self.engine.dispose()

    def _user(self, session: Session) -> User:
        user = session.get(User, self.user_id)
        self.assertIsNotNone(user)
        return user

    def test_capabilities_are_terminal_only(self) -> None:
        self.assertEqual(
            TERMINAL_BROWSER_WS_CAPABILITIES,
            frozenset({"terminal_user", "terminal_admin"}),
        )

    def test_ticket_is_extracted_from_terminal_subprotocol_offer(self) -> None:
        ticket = "A" * 43
        websocket = FakeWebSocket(f"{TERMINAL_BROWSER_WS_SUBPROTOCOL}, {ticket}")
        self.assertEqual(extract_terminal_browser_ws_ticket(websocket), ticket)
        self.assertIsNone(extract_terminal_browser_ws_ticket(FakeWebSocket(ticket)))

    def test_user_ticket_auth_returns_binding_and_selected_protocol(self) -> None:
        with Session(self.engine) as session:
            user = self._user(session)
            issued = issue_terminal_browser_ws_ticket(
                user=user,
                client_id=23,
                capability="terminal_user",
                auth_session_binding="login-session-123",
            )
            websocket = FakeWebSocket(
                f"{TERMINAL_BROWSER_WS_SUBPROTOCOL}, {issued.ticket}"
            )
            with patch(
                "service1.terminal_websocket_auth.validate_browser_auth_session_binding",
                return_value=user,
            ):
                principal, selected_protocol, binding = (
                    authenticate_terminal_browser_websocket_with_context(
                        websocket,
                        client_id=23,
                        capability="terminal_user",
                        session=session,
                    )
                )
            self.assertEqual(principal.id, self.user_id)
            self.assertEqual(selected_protocol, TERMINAL_BROWSER_WS_SUBPROTOCOL)
            self.assertEqual(binding, "login-session-123")

    def test_admin_ticket_auth_returns_binding(self) -> None:
        with Session(self.engine) as session:
            user = self._user(session)
            issued = issue_terminal_browser_ws_ticket(
                user=user,
                client_id=23,
                capability="terminal_admin",
                auth_session_binding="admin-login-session",
            )
            websocket = FakeWebSocket(
                f"{TERMINAL_BROWSER_WS_SUBPROTOCOL}, {issued.ticket}"
            )
            with patch(
                "service1.terminal_websocket_auth.validate_browser_auth_session_binding",
                return_value=user,
            ):
                principal, selected_protocol, binding = (
                    authenticate_terminal_browser_websocket_with_context(
                        websocket,
                        client_id=23,
                        capability="terminal_admin",
                        session=session,
                    )
                )
            self.assertEqual(principal.id, self.user_id)
            self.assertEqual(selected_protocol, TERMINAL_BROWSER_WS_SUBPROTOCOL)
            self.assertEqual(binding, "admin-login-session")

    def test_ticket_auth_rejects_revoked_login_binding(self) -> None:
        with Session(self.engine) as session:
            issued = issue_terminal_browser_ws_ticket(
                user=self._user(session),
                client_id=23,
                capability="terminal_admin",
                auth_session_binding="revoked-login-binding",
            )
            websocket = FakeWebSocket(
                f"{TERMINAL_BROWSER_WS_SUBPROTOCOL}, {issued.ticket}"
            )
            with patch(
                "service1.terminal_websocket_auth.validate_browser_auth_session_binding",
                return_value=None,
            ):
                principal, selected_protocol, binding = (
                    authenticate_terminal_browser_websocket_with_context(
                        websocket,
                        client_id=23,
                        capability="terminal_admin",
                        session=session,
                    )
                )
            self.assertIsNone(principal)
            self.assertIsNone(selected_protocol)
            self.assertIsNone(binding)

    def test_invalid_offered_ticket_does_not_fall_back_to_cookie(self) -> None:
        websocket = FakeWebSocket(
            f"{TERMINAL_BROWSER_WS_SUBPROTOCOL}, {'A' * 43}",
            cookie_token="platform-cookie-must-not-be-used",
        )
        with Session(self.engine) as session:
            principal, selected_protocol, binding = (
                authenticate_terminal_browser_websocket_with_context(
                    websocket,
                    client_id=23,
                    capability="terminal_user",
                    session=session,
                )
            )
        self.assertIsNone(principal)
        self.assertIsNone(selected_protocol)
        self.assertIsNone(binding)

    def test_cookie_without_terminal_ticket_is_rejected(self) -> None:
        websocket = FakeWebSocket(cookie_token="platform-cookie-must-not-be-used")
        with Session(self.engine) as session:
            principal, selected_protocol, binding = (
                authenticate_terminal_browser_websocket_with_context(
                    websocket,
                    client_id=23,
                    capability="terminal_admin",
                    session=session,
                )
            )
        self.assertIsNone(principal)
        self.assertIsNone(selected_protocol)
        self.assertIsNone(binding)

    def test_ticket_is_single_use(self) -> None:
        with Session(self.engine) as session:
            issued = issue_terminal_browser_ws_ticket(
                user=self._user(session),
                client_id=23,
                capability="terminal_user",
            )
            principal = consume_terminal_browser_ws_ticket(
                issued.ticket,
                client_id=23,
                capability="terminal_user",
                session=session,
            )
            self.assertEqual(principal.id, self.user_id)
            self.assertIsNone(
                consume_terminal_browser_ws_ticket(
                    issued.ticket,
                    client_id=23,
                    capability="terminal_user",
                    session=session,
                )
            )

    def test_wrong_mode_consumes_ticket(self) -> None:
        with Session(self.engine) as session:
            issued = issue_terminal_browser_ws_ticket(
                user=self._user(session),
                client_id=23,
                capability="terminal_user",
            )
            self.assertIsNone(
                consume_terminal_browser_ws_ticket(
                    issued.ticket,
                    client_id=23,
                    capability="terminal_admin",
                    session=session,
                )
            )
            self.assertIsNone(
                consume_terminal_browser_ws_ticket(
                    issued.ticket,
                    client_id=23,
                    capability="terminal_user",
                    session=session,
                )
            )

    def test_wrong_client_consumes_ticket(self) -> None:
        with Session(self.engine) as session:
            issued = issue_terminal_browser_ws_ticket(
                user=self._user(session),
                client_id=23,
                capability="terminal_user",
            )
            self.assertIsNone(
                consume_terminal_browser_ws_ticket(
                    issued.ticket,
                    client_id=24,
                    capability="terminal_user",
                    session=session,
                )
            )
            self.assertIsNone(
                consume_terminal_browser_ws_ticket(
                    issued.ticket,
                    client_id=23,
                    capability="terminal_user",
                    session=session,
                )
            )

    def test_expired_ticket_is_rejected(self) -> None:
        with Session(self.engine) as session:
            with patch(
                "service1.terminal_websocket_auth.time.monotonic",
                return_value=100.0,
            ):
                issued = issue_terminal_browser_ws_ticket(
                    user=self._user(session),
                    client_id=23,
                    capability="terminal_user",
                )
            with patch(
                "service1.terminal_websocket_auth.time.monotonic",
                return_value=1000.0,
            ):
                self.assertIsNone(
                    consume_terminal_browser_ws_ticket(
                        issued.ticket,
                        client_id=23,
                        capability="terminal_user",
                        session=session,
                    )
                )

    def test_user_token_version_change_invalidates_ticket(self) -> None:
        with Session(self.engine) as session:
            user = self._user(session)
            issued = issue_terminal_browser_ws_ticket(
                user=user,
                client_id=23,
                capability="terminal_admin",
            )
            user.token_version += 1
            session.add(user)
            session.commit()
            self.assertIsNone(
                consume_terminal_browser_ws_ticket(
                    issued.ticket,
                    client_id=23,
                    capability="terminal_admin",
                    session=session,
                )
            )

    def test_terminal_store_is_bounded_independently(self) -> None:
        with Session(self.engine) as session, patch(
            "service1.terminal_websocket_auth.TERMINAL_BROWSER_WS_TICKET_MAX_PENDING",
            1,
        ):
            issue_terminal_browser_ws_ticket(
                user=self._user(session),
                client_id=23,
                capability="terminal_user",
            )
            with self.assertRaises(TerminalBrowserWsTicketStoreFull):
                issue_terminal_browser_ws_ticket(
                    user=self._user(session),
                    client_id=23,
                    capability="terminal_admin",
                )

    def test_terminal_and_remote_desktop_ticket_stores_are_independent(self) -> None:
        with Session(self.engine) as session:
            user = self._user(session)
            terminal_ticket = issue_terminal_browser_ws_ticket(
                user=user,
                client_id=23,
                capability="terminal_user",
            )
            remote_ticket = issue_browser_ws_ticket(
                user=user,
                client_id=23,
                capability="remote_desktop",
            )

            _clear_terminal_browser_ws_ticket_store_for_tests()
            remote_principal = consume_browser_ws_ticket(
                remote_ticket.ticket,
                client_id=23,
                capability="remote_desktop",
                session=session,
            )
            self.assertEqual(remote_principal.id, self.user_id)
            self.assertIsNone(
                consume_terminal_browser_ws_ticket(
                    terminal_ticket.ticket,
                    client_id=23,
                    capability="terminal_user",
                    session=session,
                )
            )

            terminal_ticket = issue_terminal_browser_ws_ticket(
                user=user,
                client_id=23,
                capability="terminal_admin",
            )
            remote_ticket = issue_browser_ws_ticket(
                user=user,
                client_id=23,
                capability="remote_desktop",
            )
            _clear_browser_ws_ticket_store_for_tests()
            terminal_principal = consume_terminal_browser_ws_ticket(
                terminal_ticket.ticket,
                client_id=23,
                capability="terminal_admin",
                session=session,
            )
            self.assertEqual(terminal_principal.id, self.user_id)
            self.assertIsNone(
                consume_browser_ws_ticket(
                    remote_ticket.ticket,
                    client_id=23,
                    capability="remote_desktop",
                    session=session,
                )
            )


if __name__ == "__main__":
    unittest.main()
