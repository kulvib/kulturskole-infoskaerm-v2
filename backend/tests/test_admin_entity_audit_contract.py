from __future__ import annotations

import base64
import os
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("PASSWORD_RESET_FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")
os.environ.setdefault("HLS_BASE_DIR", "/tmp/planiq-display-ci-hls")
os.environ.setdefault(
    "LIVESTREAM_V2_CREDENTIAL_PEPPER",
    "ci-only-livestream-v2-credential-pepper-at-least-thirty-two-chars",
)
os.environ.setdefault(
    "CLIENTFLOW_ROOT_TERMINAL_KEY_B64",
    "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
)
os.environ.setdefault("CLIENTFLOW_ROOT_TERMINAL_KEY_ID", "ci-root-terminal-key-v1")

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
from service1.enrollment_models import ClientEnrollmentReceipt, ClientSystemEncryptionKey
from service1.clientflow_update_models import ClientFlowUpdateCredential
from service1.remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from service1.terminal_v2_models import TerminalClient, TerminalCredential
from service1.routers.enrollment import (
    EnrollmentClaimRequest,
    EnrollmentTokenCreate,
    _derive_resume_proof,
    claim_enrollment_token,
    create_enrollment_token,
    revoke_enrollment_token,
)
from service1.routers.organizations import (
    create_organization,
    delete_organization,
    update_organization_name,
)


TEST_SYSTEM_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAoia5/Qqkv6PJidOyW+5i
loeFlY0cp4BWfI0i2jagFRvtp9KYULb13koJGzjK9/rLdHLn2/91bKcXQnZKY6CP
ICfH5jXoscWXVCxC1DL6pQ/+R9F+lFJ1o5t2Scz52DhyWRY2XnppZ1kICniYc5yX
KVyrnYG5xNrRMTrb8r7BtDm7I3QwlYl9V96XqdrEEZRAgyZCML9ZbSjHIiI29Hu+
6q4NSY7CoxAp7oGdNsfhhPqF+Am2AtD8IJALQHWduZK0C74amXPaYNuE+Bl+x25M
TEHLgOQgYQ07E74f2bpXS9uCQciDLDSgmyGOQkAwrud1nlyYclVY9BafgeSE4nbp
eQIDAQAB
-----END PUBLIC KEY-----
"""

TEST_UPDATE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAzU6003WsShJbh/Yk3H4tAwXd4ep+A128YEJSAYemC68=
-----END PUBLIC KEY-----
"""


def _canonical_enrollment_claim(*, code: str, hostname: str, machine_id: str | None = None) -> EnrollmentClaimRequest:
    install_id = str(uuid.uuid4())
    seed = bytes(range(32))
    seed_b64 = base64.urlsafe_b64encode(seed).rstrip(b"=").decode("ascii")
    return EnrollmentClaimRequest(
        enrollment_code=code,
        install_id=install_id,
        credential_seed_b64=seed_b64,
        resume_proof=_derive_resume_proof(seed, install_id),
        system_encryption_public_key_pem=TEST_SYSTEM_PUBLIC_KEY_PEM,
        update_auth_public_key_pem=TEST_UPDATE_PUBLIC_KEY_PEM,
        hostname=hostname,
        machine_id=machine_id,
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


    def _provision_isolated_domains(self, client: Client) -> None:
        now = utcnow()
        self.session.add(TerminalClient(id=client.id, display_name=client.name, status="disabled", created_at=now))
        self.session.add(RemoteDesktopClient(id=client.id, display_name=client.name, status="disabled", created_at=now))
        self.session.flush()
        self.session.add(TerminalCredential(
            id=str(uuid.uuid4()), client_id=client.id, secret_hash="ci-terminal-secret-hash", created_at=now
        ))
        self.session.add(RemoteDesktopCredential(
            id=str(uuid.uuid4()), client_id=client.id, secret_hash="ci-rd-secret-hash", created_at=now
        ))
        self.session.commit()

    def _audit(self, action: str, entity_id: int) -> AuditLog:
        return self.session.exec(
            select(AuditLog).where(AuditLog.action == action, AuditLog.entity_id == entity_id)
        ).one()

    async def test_client_approval_rolls_back_status_and_calendar_when_audit_fails(self) -> None:
        client = self._new_client()
        client_id = client.id
        self._provision_isolated_domains(client)

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
        self._provision_isolated_domains(client)

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

        fresh_install_snapshot = {
            "target_release_id": "clientflow-1.3.0-seq-1201",
            "target_version": "1.3.0",
            "target_release_sequence": 1201,
            "bundle_sha256": "a" * 64,
            "bundle_size": 123456,
            "release_approval_reference": "51H-approved",
            "release_candidate_sha256": "b" * 64,
            "source_commit": "c" * 40,
        }

        with patch(
            "service1.routers.enrollment.fresh_install_release_snapshot",
            return_value=fresh_install_snapshot,
        ), patch(
            "service1.routers.enrollment.issue_fresh_install_authorization",
            return_value="ci-fresh-install-authorization",
        ):
            created_token = create_enrollment_token(
                _request("POST", "/api/admin/enrollment-tokens"),
                EnrollmentTokenCreate(organization_id=organization_id, expires_in_hours=1),
                self.session,
                self.admin,
            )

        enrollment_audit = self._audit("enrollment_token_created", created_token.id)
        self.assertEqual(enrollment_audit.target_organization_id, organization_id)
        self.assertEqual(
            enrollment_audit.details["fresh_install_release_id"],
            fresh_install_snapshot["target_release_id"],
        )
        self.assertEqual(
            enrollment_audit.details["fresh_install_bundle_sha256"],
            fresh_install_snapshot["bundle_sha256"],
        )
        self.assertEqual(
            enrollment_audit.details["fresh_install_approval_reference"],
            fresh_install_snapshot["release_approval_reference"],
        )
        self.assertEqual(
            enrollment_audit.details["fresh_install_source_commit"],
            fresh_install_snapshot["source_commit"],
        )

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
            _canonical_enrollment_claim(
                code=code,
                hostname="batch4-screen",
                machine_id="batch4-machine-id",
            ),
            self.session,
        )

        issuer_by_domain = {row.domain: row.token_issuer for row in response.credentials}
        self.assertEqual(issuer_by_domain["livestream"], "clientflow-api")
        self.assertEqual(issuer_by_domain["terminal"], "planiq-display-api")
        self.assertEqual(issuer_by_domain["remote_desktop"], "planiq-display-api")
        self.assertEqual(issuer_by_domain["status"], "planiq-display-api")
        self.assertEqual(issuer_by_domain["display"], "planiq-display-api")
        self.assertEqual(issuer_by_domain["system"], "planiq-display-api")

        stored_token = self.session.get(EnrollmentToken, token.id)
        stored_client = self.session.get(Client, response.client_id)
        self.assertIsNotNone(stored_client)
        self.assertIsNotNone(self.session.exec(select(ClientEnrollmentReceipt).where(ClientEnrollmentReceipt.client_id == stored_client.id)).first())
        self.assertIsNotNone(self.session.exec(select(ClientSystemEncryptionKey).where(ClientSystemEncryptionKey.client_id == stored_client.id)).first())
        update_credential = self.session.exec(
            select(ClientFlowUpdateCredential).where(
                ClientFlowUpdateCredential.client_id == stored_client.id,
                ClientFlowUpdateCredential.revoked_at == None,
            )
        ).one_or_none()
        self.assertIsNotNone(update_credential)
        self.assertEqual(response.update_auth.credential_id, update_credential.id)
        self.assertEqual(response.update_auth.key_id, update_credential.key_id)
        self.assertEqual(response.update_auth.algorithm, "Ed25519")
        self.assertIsNotNone(self.session.get(TerminalClient, stored_client.id))
        self.assertIsNotNone(self.session.get(RemoteDesktopClient, stored_client.id))
        self.assertIsNotNone(self.session.exec(select(TerminalCredential).where(TerminalCredential.client_id == stored_client.id)).first())
        self.assertIsNotNone(self.session.exec(select(RemoteDesktopCredential).where(RemoteDesktopCredential.client_id == stored_client.id)).first())
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
                    _canonical_enrollment_claim(
                        code=code,
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
