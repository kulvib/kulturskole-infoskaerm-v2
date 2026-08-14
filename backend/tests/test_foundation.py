from __future__ import annotations

from datetime import timedelta
import hashlib
import os
from pathlib import Path
import shutil
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-0123456789-0123456789")
os.environ.setdefault("CREDENTIAL_PEPPER", "test-credential-pepper-0123456789-012345")
os.environ.setdefault("PUBLIC_BASE_URL", "https://example.test")
os.environ.setdefault("HLS_ROOT", "/tmp/clientflow-foundation-tests")

import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Client, ClientDomainCredential, Organization, LivestreamGeneration, LivestreamViewer, User, utcnow
from app.security import create_client_token, credential_digest
from app.services import (
    active_viewer_count,
    claim_command,
    complete_command,
    current_generation,
    ensure_current_generation,
    maybe_recover_stale_media,
    request_restart,
    request_start,
    request_stop,
    reconcile_viewer_lifecycle,
    validate_manifest,
    viewer_enter,
    viewer_heartbeat,
    viewer_leave,
    write_hls_file,
)
from fastapi import HTTPException


class FoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        org = Organization(name="Test")
        self.db.add(org)
        self.db.flush()
        self.user = User(
            organization_id=org.id,
            email="admin@example.test",
            password_hash="unused",
            role="admin",
        )
        self.client = Client(organization_id=org.id, name="NUC")
        self.db.add_all([self.user, self.client])
        self.db.commit()
        shutil.rmtree("/tmp/clientflow-foundation-tests", ignore_errors=True)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        shutil.rmtree("/tmp/clientflow-foundation-tests", ignore_errors=True)

    def test_client_token_matches_1_2_binding_contract(self) -> None:
        secret = "cf_livestream_" + "x" * 40
        credential = ClientDomainCredential(
            id="00000000-0000-4000-8000-000000000001",
            client_id=self.client.id,
            domain="livestream",
            secret_digest=credential_digest(secret),
            token_version=3,
        )
        self.db.add(credential)
        self.db.commit()
        token, _ = create_client_token(credential)
        claims = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        self.assertEqual(claims["principal"], "client_domain")
        self.assertEqual(claims["sub"], f"client:{self.client.id}:{credential.id}")
        self.assertEqual(claims["domain"], "livestream")
        self.assertEqual(claims["scope"], "clientflow:livestream")
        self.assertIn("clientflow-domain:livestream", claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]])
        self.assertEqual(claims["token_version"], 3)
        self.assertTrue(claims["jti"])

    def test_start_claim_and_complete_matches_queue_agent_contract(self) -> None:
        generation, command = request_start(self.db, self.client.id)
        self.db.commit()
        self.assertEqual(command.command_type, "start")
        self.assertEqual(command.payload, {"generation_id": generation.id})

        claimed = claim_command(self.db, client_id=self.client.id, lease_seconds=60)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["command"]["id"], command.id)
        self.assertEqual(claimed["command"]["client_id"], self.client.id)
        self.assertEqual(claimed["command"]["command_type"], "start")
        self.assertEqual(claimed["command"]["schema_version"], 1)
        self.assertTrue(claimed["claim_token"])

        complete_command(
            self.db,
            client_id=self.client.id,
            command_id=command.id,
            claim_token=claimed["claim_token"],
            result={"generation": {"id": generation.id}},
        )
        self.db.commit()
        self.assertEqual(command.state, "completed")

    def test_restart_supersedes_old_generation_and_rejects_old_upload_generation(self) -> None:
        old, _ = request_start(self.db, self.client.id)
        self.db.commit()
        old.state = "running"
        self.db.commit()
        new, _ = request_restart(self.db, self.client.id)
        self.db.commit()
        self.assertEqual(old.state, "superseded")
        self.assertEqual(current_generation(self.db, self.client.id).id, new.id)
        with self.assertRaises(HTTPException) as caught:
            ensure_current_generation(
                self.db,
                client_id=self.client.id,
                generation_id=old.id,
                allowed_states={"starting", "running"},
            )
        self.assertEqual(caught.exception.status_code, 409)

    def test_stop_is_explicit_and_queues_even_without_active_generation(self) -> None:
        generation, command = request_stop(self.db, self.client.id)
        self.db.commit()
        self.assertIsNone(generation)
        self.assertIsNotNone(command)
        self.assertEqual(command.command_type, "stop")
        self.assertEqual(command.payload, {})

    def test_hls_upload_hash_and_manifest_contract(self) -> None:
        generation, _ = request_start(self.db, self.client.id)
        self.db.commit()
        segment = b"segment-bytes"
        digest = hashlib.sha256(segment).hexdigest()
        path = write_hls_file(
            client_id=self.client.id,
            generation_id=generation.id,
            filename="segment-000000001.ts",
            payload=segment,
            sha256=digest,
        )
        self.assertTrue(path.is_file())
        manifest = b"#EXTM3U\n#EXTINF:2,\nsegment-000000001.ts\n"
        write_hls_file(
            client_id=self.client.id,
            generation_id=generation.id,
            filename="index.m3u8",
            payload=manifest,
            sha256=hashlib.sha256(manifest).hexdigest(),
        )
        with self.assertRaises(HTTPException):
            validate_manifest(b"#EXTM3U\nhttps://evil.example/segment.ts\n")

    def test_media_watchdog_uses_upload_progress_not_process_state(self) -> None:
        viewer, generation, command = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        self.db.commit()
        claimed = claim_command(self.db, client_id=self.client.id, lease_seconds=60)
        assert claimed is not None
        complete_command(
            self.db,
            client_id=self.client.id,
            command_id=command.id,
            claim_token=claimed["claim_token"],
            result={},
        )
        generation.state = "running"
        generation.started_at = utcnow() - timedelta(seconds=90)
        generation.created_at = generation.started_at
        self.db.commit()
        self.assertTrue(maybe_recover_stale_media(self.db, self.client.id))
        self.db.commit()
        current = current_generation(self.db, self.client.id)
        self.assertIsNotNone(current)
        self.assertNotEqual(current.id, generation.id)
        self.assertEqual(current.requested_action, "reset_generation")
        self.assertEqual(generation.state, "superseded")

    def test_new_restart_cancels_older_unclaimed_generation_command(self) -> None:
        first, first_command = request_start(self.db, self.client.id)
        self.db.commit()
        second, second_command = request_restart(self.db, self.client.id)
        self.db.commit()
        self.assertEqual(first_command.state, "cancelled")
        self.assertEqual(first.state, "superseded")
        claimed = claim_command(self.db, client_id=self.client.id, lease_seconds=60)
        assert claimed is not None
        self.assertEqual(claimed["command"]["id"], second_command.id)
        self.assertEqual(claimed["command"]["payload"]["generation_id"], second.id)

    def test_stop_cancels_unclaimed_start_before_queueing_stop(self) -> None:
        generation, start_command = request_start(self.db, self.client.id)
        self.db.commit()
        stopped_generation, stop_command = request_stop(self.db, self.client.id)
        self.db.commit()
        self.assertEqual(start_command.state, "cancelled")
        self.assertEqual(stopped_generation.id, generation.id)
        self.assertEqual(generation.state, "stopping")
        claimed = claim_command(self.db, client_id=self.client.id, lease_seconds=60)
        assert claimed is not None
        self.assertEqual(claimed["command"]["id"], stop_command.id)
        self.assertEqual(claimed["command"]["command_type"], "stop")
        self.assertEqual(claimed["command"]["payload"]["generation_id"], generation.id)

    def test_media_watchdog_stops_after_three_recent_auto_recoveries(self) -> None:
        viewer, generation, command = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        self.db.commit()
        claimed = claim_command(self.db, client_id=self.client.id, lease_seconds=60)
        assert claimed is not None
        complete_command(self.db, client_id=self.client.id, command_id=command.id, claim_token=claimed["claim_token"], result={})
        generation.state = "running"
        generation.started_at = utcnow() - timedelta(seconds=90)
        generation.created_at = generation.started_at
        for index in range(3):
            self.db.add(LivestreamGeneration(
                id=f"00000000-0000-4000-8000-00000000010{index}",
                client_id=self.client.id,
                state="superseded",
                requested_action="reset_generation",
                created_at=utcnow() - timedelta(minutes=index + 1),
                superseded_at=utcnow() - timedelta(minutes=index + 1),
            ))
        self.db.commit()
        self.assertTrue(maybe_recover_stale_media(self.db, self.client.id))
        self.db.commit()
        self.assertEqual(generation.state, "failed")
        self.assertEqual(generation.error_code, "media_stalled")
        claimed_stop = claim_command(self.db, client_id=self.client.id, lease_seconds=60)
        assert claimed_stop is not None
        self.assertEqual(claimed_stop["command"]["command_type"], "stop")


    def test_first_viewer_starts_stream_and_second_viewer_shares_generation(self) -> None:
        first, generation, command = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        self.db.commit()
        self.assertIsNotNone(command)
        self.assertEqual(command.command_type, "start")
        self.assertEqual(active_viewer_count(self.db, self.client.id), 1)

        second, shared, second_command = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        self.db.commit()
        self.assertEqual(shared.id, generation.id)
        self.assertIsNone(second_command)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(active_viewer_count(self.db, self.client.id), 2)

    def test_quick_return_within_grace_keeps_same_generation(self) -> None:
        first, generation, _ = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        generation.state = "running"
        self.db.commit()

        viewer_leave(self.db, client_id=self.client.id, user_id=self.user.id, viewer_id=first.id)
        self.db.commit()
        self.assertIsNone(reconcile_viewer_lifecycle(self.db, self.client.id))
        self.db.commit()

        second, shared, command = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        self.db.commit()
        self.assertEqual(shared.id, generation.id)
        self.assertIsNone(command)
        self.assertEqual(generation.state, "running")
        self.assertNotEqual(first.id, second.id)

    def test_last_viewer_stops_only_after_grace(self) -> None:
        viewer, generation, _ = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        generation.state = "running"
        self.db.commit()
        viewer_leave(self.db, client_id=self.client.id, user_id=self.user.id, viewer_id=viewer.id)
        self.db.commit()

        self.assertIsNone(reconcile_viewer_lifecycle(self.db, self.client.id))
        self.db.commit()
        viewer.ended_at = utcnow() - timedelta(seconds=31)
        self.db.commit()
        self.assertEqual(reconcile_viewer_lifecycle(self.db, self.client.id), "stop")
        self.db.commit()
        self.assertEqual(generation.state, "stopping")

    def test_expired_lease_then_grace_stops_stream(self) -> None:
        viewer, generation, _ = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        generation.state = "running"
        viewer.last_seen_at = utcnow() - timedelta(seconds=61)
        self.db.commit()

        self.assertEqual(reconcile_viewer_lifecycle(self.db, self.client.id), "stop")
        self.db.commit()
        self.assertEqual(viewer.end_reason, "lease_expired")
        self.assertEqual(generation.state, "stopping")

    def test_heartbeat_keeps_viewer_active(self) -> None:
        viewer, generation, _ = viewer_enter(self.db, client_id=self.client.id, user_id=self.user.id)
        self.db.commit()
        before = viewer.last_seen_at
        viewer_heartbeat(
            self.db,
            client_id=self.client.id,
            user_id=self.user.id,
            viewer_id=viewer.id,
        )
        self.db.commit()
        self.assertGreaterEqual(viewer.last_seen_at, before)
        self.assertEqual(active_viewer_count(self.db, self.client.id), 1)

    def test_watchdog_does_not_reset_without_active_viewer(self) -> None:
        generation, command = request_start(self.db, self.client.id)
        self.db.commit()
        claimed = claim_command(self.db, client_id=self.client.id, lease_seconds=60)
        assert claimed is not None
        complete_command(
            self.db,
            client_id=self.client.id,
            command_id=command.id,
            claim_token=claimed["claim_token"],
            result={},
        )
        generation.state = "running"
        generation.started_at = utcnow() - timedelta(seconds=90)
        generation.created_at = generation.started_at
        self.db.commit()
        self.assertFalse(maybe_recover_stale_media(self.db, self.client.id))
        self.assertEqual(current_generation(self.db, self.client.id).id, generation.id)


if __name__ == "__main__":
    unittest.main()
