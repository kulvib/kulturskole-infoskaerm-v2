from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from service1.models import Client
from service1.livestream_v2_models import LivestreamV2Generation, LivestreamV2Viewer
from service1 import livestream_v2
from service1.routers import livestream_v2 as livestream_v2_router


class LivestreamV2ExplicitStopTests(unittest.TestCase):
    CLIENT_ID = 23
    GENERATION_ID = "11111111-1111-1111-1111-111111111111"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.safe_dir_patch = patch.object(
            livestream_v2,
            "safe_client_dir",
            side_effect=lambda client_id: str(Path(self.temp_dir.name) / str(client_id)),
        )
        self.safe_dir_patch.start()
        self.addCleanup(self.safe_dir_patch.stop)

    @staticmethod
    def principal():
        return SimpleNamespace(id=7, role="admin", is_client=False)

    def seed_running_with_viewer(self) -> None:
        with Session(self.engine) as session:
            session.add(
                Client(
                    id=self.CLIENT_ID,
                    name="Pilot 23",
                    status="approved",
                    livestream_status="running",
                    livestream_process_status="running",
                    livestream_desired_state="running",
                )
            )
            session.add(
                LivestreamV2Generation(
                    id=self.GENERATION_ID,
                    client_id=self.CLIENT_ID,
                    state="running",
                    requested_action="start",
                )
            )
            session.add(
                LivestreamV2Viewer(
                    client_id=self.CLIENT_ID,
                    viewer_id="viewer-a",
                    principal_key="admin:7",
                    source="test",
                )
            )
            session.commit()

    def request_explicit_stop(self, session: Session) -> None:
        generation, command = livestream_v2.request_stop(
            session,
            self.CLIENT_ID,
            source="browser_manual_stop",
            explicit=True,
        )
        self.assertIsNotNone(generation)
        self.assertIsNotNone(command)
        self.assertEqual(generation.state, "stopping")
        client = session.get(Client, self.CLIENT_ID)
        self.assertEqual(client.livestream_stop_reason, "explicit_stop:browser_manual_stop")
        self.assertEqual(client.livestream_desired_state, "stopped")

        livestream_v2.request_stop(
            session,
            self.CLIENT_ID,
            source="client_activity_grace_expired",
        )
        self.assertEqual(client.livestream_stop_reason, "explicit_stop:browser_manual_stop")

    def test_explicit_stop_blocks_active_viewer_until_manual_start(self) -> None:
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            self.request_explicit_stop(session)
            livestream_v2.generation_stopped(
                session,
                client_id=self.CLIENT_ID,
                generation_id=self.GENERATION_ID,
                error_code=None,
            )
            session.commit()

        with Session(self.engine) as session:
            viewer, generation, command = livestream_v2.viewer_heartbeat(
                session,
                client_id=self.CLIENT_ID,
                principal=self.principal(),
                viewer_id="viewer-a",
                source="test-heartbeat",
            )
            self.assertIsNotNone(viewer)
            self.assertIsNone(generation)
            self.assertIsNone(command)
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertIsNone(livestream_v2.reconcile_viewer_lifecycle(session, self.CLIENT_ID))
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertTrue(livestream_v2.explicit_stop_latched(session, self.CLIENT_ID))

            generation, command = livestream_v2.request_start(
                session,
                self.CLIENT_ID,
                source="browser_manual_start",
            )
            self.assertEqual(generation.state, "starting")
            self.assertIsNotNone(command)
            client = session.get(Client, self.CLIENT_ID)
            self.assertIsNone(client.livestream_stop_reason)
            self.assertEqual(client.livestream_desired_state, "running")

    def test_agent_stop_ack_does_not_restart_active_viewer_after_explicit_stop(self) -> None:
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            self.request_explicit_stop(session)
            session.commit()

        with (
            patch.object(livestream_v2_router, "engine", self.engine),
            patch.object(livestream_v2_router, "require_agent_token"),
        ):
            livestream_v2_router.agent_generation_stopped(
                self.CLIENT_ID,
                self.GENERATION_ID,
                livestream_v2_router.StoppedBody(error_code=None),
                authorization="Bearer test",
            )

        with Session(self.engine) as session:
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertTrue(livestream_v2.explicit_stop_latched(session, self.CLIENT_ID))

    def test_status_recovery_does_not_restart_after_explicit_stop(self) -> None:
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            self.request_explicit_stop(session)
            recovered = livestream_v2.reconcile_stopping_generation_from_agent_status(
                session,
                client_id=self.CLIENT_ID,
                status_payload={
                    "producer": {
                        "state": "stopped",
                        "pid": None,
                        "generation_id": self.GENERATION_ID,
                    },
                    "uploader": {
                        "state": "idle",
                        "generation_id": self.GENERATION_ID,
                    },
                },
            )
            self.assertTrue(recovered)
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertTrue(livestream_v2.explicit_stop_latched(session, self.CLIENT_ID))


if __name__ == "__main__":
    unittest.main()
