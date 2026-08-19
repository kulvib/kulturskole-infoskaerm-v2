from __future__ import annotations

import os
import unittest
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("PASSWORD_RESET_FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")
os.environ.setdefault("HLS_BASE_DIR", "/tmp/planiq-display-ci-hls")

from fastapi import Request
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from service1.auth import get_password_hash
from service1.models import (
    AuditLog,
    CalendarMarking,
    Client,
    EnrollmentToken,
    Organization,
    OrganizationCreate,
    OrganizationNameUpdate,
    User,
    utcnow,
)
from service1.rate_limit import _reset_rate_limit_state_for_tests
from service1.routers.clients import (
    ClientApprovalRequest,
    approve_client,
    purge_client,
    remove_client,
    restore_client,
    revoke_client_secret,
    rotate_client_secret,
)
from service1.routers.enrollment import (
    EnrollmentClaimRequest,
    EnrollmentTokenCreate,
    claim_enrollment_token,
    create_enrollment_token,
    revoke_enrollment_token,
)
from service1.routers.organizations import (
    create_organization,
    delete_organization,
    update_organization_name,
)


def _request(method: str = "POST", path: str = "/api/admin-contract") -> Request:
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
            "headers": [(b"user-agent", b"Batch4-CI")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        }
    )
    request.state.request_id = "batch4-audit-contract"
    return request


class AdminEntityAuditContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.organization = Organization(name="Batch 4 organisation")
        self.admin = User(
            username="batch4-admin",
            email="batch4-admin@example.invalid",
            hashed_password="hashed",
            role="superadmin",
            is_active=True,
            must_change_password=False,
        )
        self.session.add(self.organization)
        self.session.add(self.admin)
        self.session.commit()
        self.session.refresh(self.organization)
        self.session.refresh(self.admin)
        _reset_rate_limit_state_for_tests()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        _reset_rate_limit_state_for_tests()

    def _new_client(self, *, status: str = "pending") -> Client:
        client = Client(
            name="Batch 4 klient",
            status=status,
            organization_id=self.organization.id,
            isOnline=False,
        )
        self.session.add(client)
        self.session.commit()
        self.session.refresh(client)
        return client

    def _audit(self, action: str, entity_id: int) -> AuditLog:
        return self.session.exec(
            select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
        ).one()

    async def test_client_approval_rolls_back_status_and_calendar_when_audit_fails(self) -> None:
        client = self._new_client()
        client_id = client.id

        with patch(
            "service1.routers.clients.add_audit_log",
            side_effect=RuntimeError("forced-approval-audit-failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "forced-approval-audit-failure"):
                await approve_client(
                    _request("POST", f"/api/clients/{client_id}/approve"),
                    client_id,
                    ClientApprovalRequest(organization_id=self.organization.id),
                    self.session,
                    self.admin,
                )

        self.session.rollback()
        stored_client = self.session.get(Client, client_id)
        calendar = self.session.exec(
            select(CalendarMarking).where(CalendarMarking.client_id == client_id)
        ).first()
        self.assertEqual(stored_client.status, "pending")
        self.assertIsNone(calendar)

    async def test_client_lifecycle_and_secret_changes_are_audited(self) -> None:
        client = self._new_client(status="approved")
        client_id = client.id

        rotated = rotate_client_secret(
            _request("POST", f"/api/clients/{client_id}/client-secret/rotate"),
            client_id,
            self.session,
            self.admin,
        )
        self.assertTrue(rotated["client_secret"].startswith("cf_client_"))
        rotate_audit = self._audit("client_secret_rotated", client_id)
        self.assertTrue(rotate_audit.is_critical)
        self.assertNotIn("client_secret", rotate_audit.details or {})

        revoke_client_secret(
            _request("POST", f"/api/clients/{client_id}/client-secret/revoke"),
            client_id,
            self.session,
            self.admin,
        )
        self.assertTrue(self._audit("client_secret_revoked", client_id).is_critical)

        await remove_client(
            _request("DELETE", f"/api/clients/{client_id}/remove"),
            client_id,
            {"reason": "CI cleanup"},
            self.session,
            self.admin,
        )
        soft_delete_audit = self._audit("client_soft_deleted", client_id)
        self.assertEqual(soft_delete_audit.severity, "warning")
        self.assertEqual(soft_delete_audit.details["reason"], "CI cleanup")

        await restore_client(
            _request("POST", f"/api/clients/{client_id}/restore"),
            client_id,
            self.session,
            self.admin,
        )
        self.assertEqual(self._audit("client_restored", client_id).details["restored_status"], "approved")

        await remove_client(
            _request("DELETE", f"/api/clients/{client_id}/remove"),
            client_id,
            None,
            self.session,
            self.admin,
        )
        await purge_client(
            _request("DELETE", f"/api/clients/{client_id}/purge"),
            client_id,
            self.session,
            self.admin,
        )

        self.assertIsNone(self.session.get(Client, client_id))
        purge_audit = self._audit("client_permanently_deleted", client_id)
        self.assertTrue(purge_audit.is_critical)
        self.assertEqual(purge_audit.actor_user_id, self.admin.id)

    async def test_client_approval_and_calendar_creation_share_one_commit(self) -> None:
        client = self._new_client()
        client_id = client.id

        approved = await approve_client(
            _request("POST", f"/api/clients/{client_id}/approve"),
            client_id,
            ClientApprovalRequest(organization_id=self.organization.id),
            self.session,
            self.admin,
        )

        self.assertEqual(approved.status, "approved")
        calendars = self.session.exec(
            select(CalendarMarking).where(CalendarMarking.client_id == client_id)
        ).all()
        audit = self._audit("client_approved", client_id)
        self.assertEqual(len(calendars), 2)
        self.assertEqual(
            {item["season"] for item in audit.details["calendar_seasons"]},
            {calendar.season for calendar in calendars},
        )
        self.assertTrue(all(item["created"] for item in audit.details["calendar_seasons"]))

    async def test_organization_and_enrollment_admin_changes_are_audited(self) -> None:
        created = create_organization(
            _request("POST", "/api/organizations/"),
            OrganizationCreate(name="Audit organisation"),
            self.session,
            self.admin,
        )
        organization_id = created["id"] if isinstance(created, dict) else created.id
        self.assertEqual(self._audit("organization_created", organization_id).entity_label, "Audit organisation")

        renamed = update_organization_name(
            _request("PATCH", f"/api/organizations/{organization_id}/"),
            organization_id,
            OrganizationNameUpdate(name="Audit organisation renamed"),
            self.session,
            self.admin,
        )
        renamed_name = renamed["name"] if isinstance(renamed, dict) else renamed.name
        self.assertEqual(renamed_name, "Audit organisation renamed")
        rename_audit = self._audit("organization_name_changed", organization_id)
        self.assertEqual(rename_audit.details["name_before"], "Audit organisation")
        self.assertEqual(rename_audit.details["name_after"], "Audit organisation renamed")

        created_token = create_enrollment_token(
            _request("POST", "/api/admin/enrollment-tokens"),
            EnrollmentTokenCreate(organization_id=organization_id, expires_in_hours=1),
            self.session,
            self.admin,
        )
        self.assertEqual(self._audit("enrollment_token_created", created_token.id).target_organization_id, organization_id)

        revoked = revoke_enrollment_token(
            _request("POST", f"/api/admin/enrollment-tokens/{created_token.id}/revoke"),
            created_token.id,
            self.session,
            self.admin,
        )
        self.assertTrue(revoked.is_revoked)
        self.assertEqual(self._audit("enrollment_token_revoked", created_token.id).severity, "warning")

        delete_organization(
            _request("DELETE", f"/api/organizations/{organization_id}/"),
            organization_id,
            self.session,
            self.admin,
        )
        self.assertIsNone(self.session.get(Organization, organization_id))
        self.assertTrue(self._audit("organization_deleted", organization_id).is_critical)

    async def test_enrollment_claim_is_atomic_and_audited(self) -> None:
        code = "CF-ABCD-1234-WXYZ"
        token = EnrollmentToken(
            code_hash=get_password_hash(code),
            code_preview="WXYZ",
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(hours=1),
            created_by_user_id=self.admin.id,
            organization_id=self.organization.id,
        )
        self.session.add(token)
        self.session.commit()
        self.session.refresh(token)

        response = claim_enrollment_token(
            _request("POST", "/api/enrollment/claim"),
            EnrollmentClaimRequest(
                enrollment_code=code,
                hostname="batch4-screen",
                machine_id="batch4-machine-id",
            ),
            self.session,
        )

        stored_token = self.session.get(EnrollmentToken, token.id)
        stored_client = self.session.get(Client, response.client_id)
        self.assertIsNotNone(stored_client)
        self.assertEqual(stored_token.used_by_client_id, stored_client.id)
        self.assertIsNotNone(stored_token.used_at)
        self.assertEqual(self._audit("client_enrolled", stored_client.id).details["enrollment_token_id"], token.id)

    async def test_enrollment_claim_rolls_back_client_and_token_when_audit_fails(self) -> None:
        code = "CF-ZZZZ-9999-ROLL"
        token = EnrollmentToken(
            code_hash=get_password_hash(code),
            code_preview="ROLL",
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(hours=1),
            created_by_user_id=self.admin.id,
            organization_id=self.organization.id,
        )
        self.session.add(token)
        self.session.commit()
        self.session.refresh(token)
        token_id = token.id

        with patch(
            "service1.routers.enrollment.add_audit_log",
            side_effect=RuntimeError("forced-audit-failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "forced-audit-failure"):
                claim_enrollment_token(
                    _request("POST", "/api/enrollment/claim"),
                    EnrollmentClaimRequest(
                        enrollment_code=code,
                        hostname="must-not-persist",
                    ),
                    self.session,
                )

        self.session.rollback()
        stored_token = self.session.get(EnrollmentToken, token_id)
        persisted_client = self.session.exec(
            select(Client).where(Client.name == "must-not-persist")
        ).first()
        self.assertIsNone(persisted_client)
        self.assertIsNone(stored_token.used_at)
        self.assertIsNone(stored_token.used_by_client_id)


if __name__ == "__main__":
    unittest.main()
