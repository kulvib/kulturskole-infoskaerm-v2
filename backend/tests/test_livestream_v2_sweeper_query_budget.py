from __future__ import annotations

from datetime import timedelta
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from service1 import livestream_v2
from service1.client_activity_models import ClientActivityLease
from service1.livestream_v2_models import LivestreamV2Generation, LivestreamV2Viewer
from service1.models import Client


class LivestreamV2SweeperQueryBudgetTests(unittest.TestCase):
    CLIENT_ID = 91
    GENERATION_ID = "99999999-9999-9999-9999-999999999999"

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def seed_client(self, session: Session) -> None:
        session.add(Client(id=self.CLIENT_ID, name="Query budget", status="approved"))

    def seed_running_generation(self, session: Session) -> None:
        session.add(
            LivestreamV2Generation(
                id=self.GENERATION_ID,
                client_id=self.CLIENT_ID,
                state="running",
                requested_action="start",
            )
        )

    def test_running_generation_with_live_viewer_skips_per_client_reconcile(self) -> None:
        with Session(self.engine) as session:
            self.seed_client(session)
            self.seed_running_generation(session)
            session.add(
                LivestreamV2Viewer(
                    client_id=self.CLIENT_ID,
                    viewer_id="viewer-live",
                    principal_key="admin:1",
                    last_seen_at=livestream_v2._now(),
                )
            )
            session.commit()

            with patch.object(livestream_v2, "reconcile_viewer_lifecycle") as reconcile:
                self.assertEqual(livestream_v2.reconcile_all_viewer_lifecycles(session), [])
                reconcile.assert_not_called()

    def test_running_generation_with_live_activity_skips_per_client_reconcile(self) -> None:
        with Session(self.engine) as session:
            self.seed_client(session)
            self.seed_running_generation(session)
            session.add(
                ClientActivityLease(
                    id="activity-91",
                    client_id=self.CLIENT_ID,
                    domain="terminal",
                    session_id="session-91",
                    last_seen_at=livestream_v2._now(),
                )
            )
            session.commit()

            with patch.object(livestream_v2, "reconcile_viewer_lifecycle") as reconcile:
                self.assertEqual(livestream_v2.reconcile_all_viewer_lifecycles(session), [])
                reconcile.assert_not_called()

    def test_stale_viewer_is_expired_before_steady_state_fast_path(self) -> None:
        stale_seen = livestream_v2._now() - timedelta(
            seconds=livestream_v2.VIEWER_LEASE_SECONDS + 1
        )
        with Session(self.engine) as session:
            self.seed_client(session)
            self.seed_running_generation(session)
            session.add(
                LivestreamV2Viewer(
                    client_id=self.CLIENT_ID,
                    viewer_id="viewer-stale",
                    principal_key="admin:1",
                    last_seen_at=stale_seen,
                )
            )
            session.commit()

            with patch.object(
                livestream_v2,
                "reconcile_viewer_lifecycle",
                return_value=None,
            ) as reconcile:
                self.assertEqual(livestream_v2.reconcile_all_viewer_lifecycles(session), [])
                reconcile.assert_called_once_with(session, self.CLIENT_ID)

            viewer = session.exec(
                select(LivestreamV2Viewer).where(
                    LivestreamV2Viewer.client_id == self.CLIENT_ID,
                    LivestreamV2Viewer.viewer_id == "viewer-stale",
                )
            ).one()
            self.assertIsNotNone(viewer.ended_at)
            self.assertEqual(viewer.end_reason, "lease_expired")

    def test_live_presence_without_generation_keeps_transition_reconcile(self) -> None:
        with Session(self.engine) as session:
            self.seed_client(session)
            session.add(
                LivestreamV2Viewer(
                    client_id=self.CLIENT_ID,
                    viewer_id="viewer-start",
                    principal_key="admin:1",
                    last_seen_at=livestream_v2._now(),
                )
            )
            session.commit()

            with patch.object(
                livestream_v2,
                "reconcile_viewer_lifecycle",
                return_value="start",
            ) as reconcile:
                self.assertEqual(
                    livestream_v2.reconcile_all_viewer_lifecycles(session),
                    [(self.CLIENT_ID, "start")],
                )
                reconcile.assert_called_once_with(session, self.CLIENT_ID)


if __name__ == "__main__":
    unittest.main()
