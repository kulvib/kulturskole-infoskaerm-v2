from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "backend/service1/routers/calendar.py"
ORGANIZATIONS = ROOT / "backend/service1/routers/organizations.py"


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            lines = source.splitlines()
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"Function {name!r} not found in {path}")


def test_save_marked_days_batches_client_and_calendar_reads() -> None:
    source = _function_source(CALENDAR, "save_marked_days")

    assert "select(Client.id, Client.organization_id)" in source
    assert "Client.id.in_(unique_client_ids)" in source
    assert "CalendarMarking.client_id.in_(unique_client_ids)" in source
    assert "client_organization_by_id" in source
    assert "existing_by_client" in source
    assert "session.get(Client, client_id)" not in source
    assert "CalendarMarking.client_id == client_id" not in source


def test_season_summary_projects_only_needed_columns_and_never_loads_calendar_json(
) -> None:
    source = _function_source(ORGANIZATIONS, "get_organization_season_summary")

    assert "select(Organization.id, Organization.name)" in source
    assert (
        "select(OrganizationSeasonTimes.season, OrganizationSeasonTimes.organization_id)"
        in source
    )
    assert "select(CalendarMarking.season, Client.organization_id)" in source
    assert ".join(Client, Client.id == CalendarMarking.client_id)" in source
    assert "select(CalendarMarking)).all()" not in source
    assert "select(Client)).all()" not in source
    assert "marking.markings" not in source
    assert "row.markings" not in source


def test_apply_season_times_batches_existing_calendars_before_client_loop() -> None:
    source = _function_source(ORGANIZATIONS, "apply_organization_season_times")

    assert "select(Client.id).where(" in source
    assert "CalendarMarking.client_id.in_(client_ids)" in source
    assert "existing_by_client" in source
    loop = source.index("for client_id in client_ids:")
    assert source.index("existing_by_client", 0, loop) >= 0
    assert "session.exec(" not in source[loop:]


def test_replace_season_calendars_batches_existing_calendars_before_client_loop(
) -> None:
    source = _function_source(ORGANIZATIONS, "replace_organization_season_calendars")

    assert "select(Client.id).where(" in source
    assert "CalendarMarking.client_id.in_(client_ids)" in source
    assert "existing_by_client" in source
    loop = source.index("for client_id in client_ids:")
    assert source.index("existing_by_client", 0, loop) >= 0
    assert "session.exec(" not in source[loop:]
