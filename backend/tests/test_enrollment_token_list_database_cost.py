from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine

from service1.models import Client, EnrollmentToken, utcnow
from service1.routers import enrollment as enrollment_router


def _seed_used_tokens(engine, count: int) -> None:
    now = utcnow()
    with Session(engine) as session:
        for index in range(count):
            client = Client(
                name=f"enrollment-perf-{index:03d}",
                locality=f"room-{index:03d}",
                status="approved",
            )
            session.add(client)
            session.flush()
            session.add(
                EnrollmentToken(
                    code_hash=f"hash-{index}",
                    code_preview=f"{index:04d}",
                    created_at=now - timedelta(seconds=index),
                    expires_at=now + timedelta(hours=1),
                    used_at=now,
                    used_by_client_id=int(client.id),
                )
            )
        session.commit()


@pytest.mark.parametrize("token_count", [1, 10, 50, 100])
def test_enrollment_token_list_query_count_is_constant(token_count: int) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    _seed_used_tokens(engine, token_count)

    select_count = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        with Session(engine) as session:
            result = enrollment_router.list_enrollment_tokens(
                include_history=False,
                session=session,
                admin=SimpleNamespace(is_superadmin=True),
            )
            assert len(result) == token_count
            assert result[0].used_by_client_name == "enrollment-perf-000"
            assert result[0].used_by_client_locality == "room-000"
            assert result[0].used_by_client_status == "approved"
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert select_count == 1


def test_enrollment_token_list_keeps_history_filter_semantics_in_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    now = utcnow()

    with Session(engine) as session:
        client = Client(name="used-client", locality="used-room", status="approved")
        session.add(client)
        session.flush()
        rows = [
            EnrollmentToken(
                code_hash="active",
                code_preview="0001",
                created_at=now,
                expires_at=now + timedelta(hours=1),
            ),
            EnrollmentToken(
                code_hash="used",
                code_preview="0002",
                created_at=now - timedelta(seconds=1),
                expires_at=now - timedelta(hours=1),
                used_at=now,
                used_by_client_id=int(client.id),
            ),
            EnrollmentToken(
                code_hash="expired",
                code_preview="0003",
                created_at=now - timedelta(seconds=2),
                expires_at=now - timedelta(hours=1),
            ),
            EnrollmentToken(
                code_hash="revoked",
                code_preview="0004",
                created_at=now - timedelta(seconds=3),
                expires_at=now + timedelta(hours=1),
                revoked_at=now,
            ),
        ]
        session.add_all(rows)
        session.commit()

    with Session(engine) as session:
        current = enrollment_router.list_enrollment_tokens(
            include_history=False,
            session=session,
            admin=SimpleNamespace(is_superadmin=True),
        )
        history = enrollment_router.list_enrollment_tokens(
            include_history=True,
            session=session,
            admin=SimpleNamespace(is_superadmin=True),
        )

    assert [row.code_preview for row in current] == ["0001", "0002"]
    assert [row.code_preview for row in history] == ["0001", "0002", "0003", "0004"]
    used = next(row for row in current if row.code_preview == "0002")
    assert used.used_by_client_name == "used-client"
    assert used.used_by_client_locality == "used-room"
    assert used.used_by_client_status == "approved"
