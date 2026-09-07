from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from service1.models import User
from service1.websocket_auth import (
    BROWSER_WS_CAPABILITIES,
    BROWSER_WS_SUBPROTOCOL,
    _clear_browser_ws_ticket_store_for_tests,
    authenticate_browser_websocket,
    consume_browser_ws_ticket,
    extract_browser_ws_ticket,
    issue_browser_ws_ticket,
)


class FakeWebSocket:
    def __init__(self, protocols: str = "", cookie_token: str = ""):
        self.headers = {"sec-websocket-protocol": protocols} if protocols else {}
        self.cookies = {"access_token": cookie_token} if cookie_token else {}
        self.query_params = {}


class BrowserWebSocketTicketTests(unittest.TestCase):
    def setUp(self) -> None:
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
        _clear_browser_ws_ticket_store_for_tests()
        self.engine.dispose()

    def _user(self, session: Session) -> User:
        user = session.get(User, self.user_id)
        self.assertIsNotNone(user)
        return user

    def test_shared_browser_ticket_capability_is_remote_desktop_only(self) -> None:
        self.assertEqual(BROWSER_WS_CAPABILITIES, frozenset({"remote_desktop"}))

    def test_ticket_is_extracted_from_subprotocol_offer(self) -> None:
        ticket = "A" * 43
        websocket = FakeWebSocket(f"{BROWSER_WS_SUBPROTOCOL}, {ticket}")
        self.assertEqual(extract_browser_ws_ticket(websocket), ticket)
        self.assertIsNone(extract_browser_ws_ticket(FakeWebSocket(ticket)))

    def test_direct_ticket_auth_returns_selected_marker_protocol(self) -> None:
        with Session(self.engine) as session:
            user = self._user(session)
            issued = issue_browser_ws_ticket(
                user=user,
                client_id=22,
                capability="remote_desktop",
                auth_session_binding="active-login-binding",
            )
            websocket = FakeWebSocket(f"{BROWSER_WS_SUBPROTOCOL}, {issued.ticket}")
            with patch(
                "service1.websocket_auth.validate_browser_auth_session_binding",
                return_value=user,
            ):
                principal, selected_protocol = authenticate_browser_websocket(
                    websocket,
                    client_id=22,
                    capability="remote_desktop",
                    session=session,
                )
            self.assertEqual(principal.id, self.user_id)
            self.assertEqual(selected_protocol, BROWSER_WS_SUBPROTOCOL)

    def test_ticket_auth_rejects_revoked_login_binding(self) -> None:
        with Session(self.engine) as session:
            issued = issue_browser_ws_ticket(
                user=self._user(session),
                client_id=22,
                capability="remote_desktop",
                auth_session_binding="revoked-login-binding",
            )
            websocket = FakeWebSocket(f"{BROWSER_WS_SUBPROTOCOL}, {issued.ticket}")
            with patch(
                "service1.websocket_auth.validate_browser_auth_session_binding",
                return_value=None,
            ):
                principal, selected_protocol = authenticate_browser_websocket(
                    websocket,
                    client_id=22,
                    capability="remote_desktop",
                    session=session,
                )
            self.assertIsNone(principal)
            self.assertIsNone(selected_protocol)

    def test_invalid_offered_ticket_does_not_fall_back_to_cookie(self) -> None:
        websocket = FakeWebSocket(
            f"{BROWSER_WS_SUBPROTOCOL}, {'A' * 43}",
            cookie_token="valid-cookie-that-must-not-be-used",
        )
        with Session(self.engine) as session, patch(
            "service1.websocket_auth.verify_ws_token"
        ) as verify_token:
            principal, selected_protocol = authenticate_browser_websocket(
                websocket,
                client_id=22,
                capability="remote_desktop",
                session=session,
            )
        self.assertIsNone(principal)
        self.assertIsNone(selected_protocol)
        verify_token.assert_not_called()

    def test_ticket_is_bound_to_client_and_single_use(self) -> None:
        with Session(self.engine) as session:
            issued = issue_browser_ws_ticket(
                user=self._user(session),
                client_id=22,
                capability="remote_desktop",
            )
            principal = consume_browser_ws_ticket(
                issued.ticket,
                client_id=22,
                capability="remote_desktop",
                session=session,
            )
            self.assertEqual(principal.id, self.user_id)
            self.assertIsNone(
                consume_browser_ws_ticket(
                    issued.ticket,
                    client_id=22,
                    capability="remote_desktop",
                    session=session,
                )
            )

    def test_wrong_client_consumes_ticket(self) -> None:
        with Session(self.engine) as session:
            issued = issue_browser_ws_ticket(
                user=self._user(session),
                client_id=22,
                capability="remote_desktop",
            )
            self.assertIsNone(
                consume_browser_ws_ticket(
                    issued.ticket,
                    client_id=23,
                    capability="remote_desktop",
                    session=session,
                )
            )
            self.assertIsNone(
                consume_browser_ws_ticket(
                    issued.ticket,
                    client_id=22,
                    capability="remote_desktop",
                    session=session,
                )
            )

    def test_terminal_capabilities_cannot_be_issued_from_shared_store(self) -> None:
        with Session(self.engine) as session:
            with self.assertRaises(ValueError):
                issue_browser_ws_ticket(
                    user=self._user(session),
                    client_id=22,
                    capability="terminal_user",
                )

    def test_expired_ticket_is_rejected(self) -> None:
        with Session(self.engine) as session:
            with patch("service1.websocket_auth.time.monotonic", return_value=100.0):
                issued = issue_browser_ws_ticket(
                    user=self._user(session),
                    client_id=22,
                    capability="remote_desktop",
                )
            with patch("service1.websocket_auth.time.monotonic", return_value=1000.0):
                self.assertIsNone(
                    consume_browser_ws_ticket(
                        issued.ticket,
                        client_id=22,
                        capability="remote_desktop",
                        session=session,
                    )
                )

    def test_user_token_version_change_invalidates_ticket(self) -> None:
        with Session(self.engine) as session:
            user = self._user(session)
            issued = issue_browser_ws_ticket(
                user=user,
                client_id=22,
                capability="remote_desktop",
            )
            user.token_version += 1
            session.add(user)
            session.commit()
            self.assertIsNone(
                consume_browser_ws_ticket(
                    issued.ticket,
                    client_id=22,
                    capability="remote_desktop",
                    session=session,
                )
            )


if __name__ == "__main__":
    unittest.main()
