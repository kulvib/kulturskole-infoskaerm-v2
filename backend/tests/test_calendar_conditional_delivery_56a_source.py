from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_56a_migration_is_additive_and_is_current_head() -> None:
    migration = read("backend/migrations/versions/20260922_56a_calendar_rev.py")
    contract = read("backend/scripts/display_schema_contract.py")
    runner = read("backend/scripts/run_migrations.py")
    model = read("backend/service1/models.py")

    assert 'revision = "20260922_56a_calendar_rev"' in migration
    assert 'down_revision = "20260908_55a_enroll_binding"' in migration
    assert 'op.add_column(' in migration and '"updated_at"' in migration
    assert 'UPDATE calendarmarking SET updated_at = CURRENT_TIMESTAMP' in migration
    assert 'op.alter_column("calendarmarking", "updated_at", nullable=False)' in migration
    assert contract.rsplit("EXPECTED_HEAD_REVISION = ", 1)[1].splitlines()[0] == '"20260922_56a_calendar_rev"'
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260922_56a_calendar_rev"' in runner
    assert 'REVIEWED_LEGACY_RECONCILIATION_HEAD = "20260922_56a_calendar_rev"' in runner
    assert 'REVIEWED_CALENDAR_DELIVERY_REVISION = "20260922_56a_calendar_rev"' in runner
    assert 'calendar_delivery_revision.down_revision != REVIEWED_ENROLLMENT_BINDING_REVISION' in runner
    assert 'updated_at: datetime = Field(' in model
    assert 'onupdate=utcnow' in model


def test_56a_calendar_conditional_delivery_reads_metadata_without_markings() -> None:
    control = read("backend/service1/calendar_control.py")
    route = read("backend/service1/routers/shared_domain.py")
    agent = read("client/runtime/clientflow_runtime/calendar_agent.py")

    assert 'def display_calendar_delivery_etag(' in control
    metadata_block = control[
        control.index('def display_calendar_delivery_etag('):
        control.index('def build_display_calendar_delivery_with_etag(')
    ]
    assert 'CalendarMarking.id' in metadata_block
    assert 'CalendarMarking.season' in metadata_block
    assert 'CalendarMarking.updated_at' in metadata_block
    assert 'CalendarMarking.markings' not in metadata_block

    assert 'alias="If-None-Match"' in route
    assert 'status_code=304' in route
    assert '"ETag": current_etag' in route
    assert 'build_display_calendar_delivery_with_etag(' in route
    assert 'Cache-Control": "private, no-cache"' in route

    assert 'expected=(200, 304)' in agent
    assert '"If-None-Match": etag' in agent
    assert 'if response.status_code == 304:' in agent
    assert 'atomic_write_json(CACHE_PATH, plan, mode=0o600)' in agent
    assert 'if changed:' in agent


def test_56a_changed_snapshot_still_validates_complete_calendar_and_content_revision() -> None:
    control = read("backend/service1/calendar_control.py")
    assert 'require_complete=True' in control
    assert '"revision": _revision_for(seasons)' in control
    assert 'status_code=409' in control
    assert 'current_and_next_seasons()' in control


def test_56a_modified_python_sources_parse() -> None:
    for relative in (
        "backend/service1/models.py",
        "backend/service1/calendar_control.py",
        "backend/service1/routers/shared_domain.py",
        "backend/migrations/versions/20260922_56a_calendar_rev.py",
        "backend/scripts/run_migrations.py",
        "backend/scripts/calendar_delivery_schema_contract.py",
        "backend/scripts/display_schema_contract.py",
        "client/runtime/clientflow_runtime/calendar_agent.py",
    ):
        ast.parse(read(relative), filename=relative)
