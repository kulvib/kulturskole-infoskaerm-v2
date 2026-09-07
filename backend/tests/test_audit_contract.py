from __future__ import annotations

import json
import os
import unittest
from unittest.mock import AsyncMock, patch
from datetime import datetime

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("PASSWORD_RESET_FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")
os.environ.setdefault("HLS_BASE_DIR", "/tmp/planiq-display-ci-hls")

from fastapi import HTTPException, Request, Response
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from service1.audit import add_audit_log
from service1.auth import get_password_hash, login_for_access_token
from service1.models import AuditLog, RefreshToken, User
from service1.routers.users import AuditLogOut, AuditLogRetentionOut, UserCreate, create_user, delete_user, list_audit_logs
from fastapi.security import OAuth2PasswordRequestForm


def _request(
    method: str = "POST",
    path: str = "/api/users/",
    request_id: str | None = None,
) -> Request:
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"user-agent", b"Step34A-CI")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        }
    )
    if request_id is not None:
        request.state.request_id = request_id
    return request


class AuditContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(
            self.engine,
            tables=[User.__table__, RefreshToken.__table__, AuditLog.__table__],
        )
        self.session = Session(self.engine)
        self.admin = User(
            username="audit-admin",
            email="audit-admin@example.invalid",
            hashed_password="hashed",
            role="superadmin",
            is_active=True,
            must_change_password=False,
        )
        self.session.add(self.admin)
        self.session.commit()
        self.session.refresh(self.admin)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    async def test_audit_row_captures_validated_request_id(self) -> None:
        request = _request(request_id="audit-correlation-123")
        row = add_audit_log(
            self.session,
            action="user_updated",
            request=request,
            entity_type="user",
            entity_id=42,
        )
        self.session.commit()

        stored = self.session.exec(select(AuditLog).where(AuditLog.id == row.id)).one()
        self.assertEqual(stored.request_id, "audit-correlation-123")

    async def test_legacy_delete_deactivates_and_writes_audit_in_same_commit(self) -> None:
        target = User(
            username="audit-target",
            email="audit-target@example.invalid",
            hashed_password="hashed",
            role="bruger",
            is_active=True,
            must_change_password=False,
        )
        self.session.add(target)
        self.session.commit()
        self.session.refresh(target)
        target_id = target.id

        delete_user(_request("DELETE", f"/api/users/{target_id}"), target_id, self.session, self.admin)

        stored = self.session.get(User, target_id)
        self.assertIsNotNone(stored)
        self.assertFalse(stored.is_active)
        self.assertTrue(stored.must_change_password)
        audit = self.session.exec(
            select(AuditLog).where(AuditLog.action == "user_deactivated", AuditLog.entity_id == target_id)
        ).one()
        self.assertEqual(audit.actor_user_id, self.admin.id)
        self.assertEqual(audit.details["source"], "legacy_delete_route")

    async def test_user_creation_is_audited_when_activation_email_fails(self) -> None:
        payload = UserCreate(
            username="mail-failure-user",
            email="mail-failure@example.invalid",
            role="bruger",
            organization_id=1,
            is_active=True,
        )

        with patch("service1.routers.users.get_password_hash", return_value="hashed"), patch(
            "service1.routers.users._send_password_reset_link",
            new=AsyncMock(side_effect=RuntimeError("sensitive-mail-provider-error")),
        ):
            with self.assertRaises(HTTPException) as raised:
                await create_user(_request(), payload, self.session, self.admin)

        self.assertEqual(raised.exception.status_code, 500)
        created = self.session.exec(select(User).where(User.username == "mail-failure-user")).one()
        audit = self.session.exec(
            select(AuditLog).where(AuditLog.action == "user_created", AuditLog.entity_id == created.id)
        ).one()
        self.assertEqual(audit.status, "partial")
        self.assertEqual(audit.details["activation_email_sent"], False)


    async def test_successful_login_is_committed_and_returned_as_newest_audit_row(self) -> None:
        self.admin.hashed_password = get_password_hash("correct-password-123")
        self.session.add(self.admin)
        self.session.commit()

        form = OAuth2PasswordRequestForm(
            username=self.admin.username,
            password="correct-password-123",
            scope="",
            client_id=None,
            client_secret=None,
        )
        login_for_access_token(Response(), _request("POST", "/api/auth/token"), form, self.session)

        response = Response()
        rows = list_audit_logs(
            response=response,
            limit=10,
            session=self.session,
            current_user=self.admin,
        )

        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0].action, "login_success")
        self.assertEqual(rows[0].actor_user_id, self.admin.id)
        self.assertEqual(rows[0].target_user_id, self.admin.id)
        self.assertEqual(rows[0].entity_id, self.admin.id)
        self.assertIn("no-store", response.headers.get("cache-control", ""))


    async def test_audit_api_serializes_utc_datetimes_with_z_suffix(self) -> None:
        row = AuditLog(
            id=123,
            action="login_success",
            created_at=datetime(2026, 7, 12, 14, 55, 47),
            retain_until=datetime(2026, 10, 10, 14, 55, 47),
            request_id="audit-correlation-123",
        )
        payload = json.loads(AuditLogOut.model_validate(row).model_dump_json())
        self.assertEqual(payload["created_at"], "2026-07-12T14:55:47Z")
        self.assertEqual(payload["retain_until"], "2026-10-10T14:55:47Z")
        self.assertEqual(payload["request_id"], "audit-correlation-123")

        retention = json.loads(
            AuditLogRetentionOut(
                retention_days=90,
                expired_count=0,
                now=datetime(2026, 7, 12, 14, 55, 47),
            ).model_dump_json()
        )
        self.assertEqual(retention["now"], "2026-07-12T14:55:47Z")

    async def test_entity_id_filter_returns_only_selected_user_history(self) -> None:
        first = AuditLog(action="user_updated", entity_type="user", entity_id=10)
        second = AuditLog(action="user_updated", entity_type="user", entity_id=20)
        self.session.add(first)
        self.session.add(second)
        self.session.commit()

        rows = list_audit_logs(
            response=Response(),
            entity_type="user",
            entity_id=20,
            session=self.session,
            current_user=self.admin,
        )
        self.assertEqual([row.entity_id for row in rows], [20])


if __name__ == "__main__":
    unittest.main()
