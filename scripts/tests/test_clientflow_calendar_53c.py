from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_calendar_runtime_sources_compile_as_python() -> None:
    for relative in (
        "client/runtime/clientflow_runtime/calendar_agent.py",
        "client/runtime/clientflow_runtime/display_local_control.py",
        "client/runtime/clientflow_runtime/display_agent.py",
        "backend/service1/calendar_control.py",
    ):
        ast.parse(source(relative), filename=relative)


def test_calendar_service_does_not_use_legacy_client_secret_or_live_system_control() -> None:
    calendar = source("client/runtime/clientflow_runtime/calendar_agent.py")
    service = source("client/systemd/clientflow-calendar.service")
    assert "client_secret" not in calendar.lower()
    assert "client-token" not in calendar.lower()
    assert "systemctl" not in calendar.lower()
    assert "LoadCredential=display.json" in service


def test_calendar_wall_clock_evaluation_is_exact_and_off_days_stay_off() -> None:
    import hashlib
    import json
    import sys
    from datetime import datetime

    runtime_root = str(ROOT / "client/runtime")
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    from clientflow_runtime import calendar_agent

    seasons = {
        "2026/2027": {
            "2026-08-24": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
            "2026-08-25": {"status": "off"},
        }
    }
    revision = hashlib.sha256(
        json.dumps(seasons, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    plan = calendar_agent._validate_plan(
        {"schema_version": 1, "client_id": 7, "revision": revision, "seasons": seasons},
        client_id=7,
    )

    assert calendar_agent._desired_state(plan, datetime(2026, 8, 24, 8, 59, 59)) == "off"
    assert calendar_agent._desired_state(plan, datetime(2026, 8, 24, 9, 0, 0)) == "on"
    assert calendar_agent._desired_state(plan, datetime(2026, 8, 24, 19, 59, 59)) == "on"
    assert calendar_agent._desired_state(plan, datetime(2026, 8, 24, 20, 0, 0)) == "off"
    assert calendar_agent._desired_state(plan, datetime(2026, 8, 25, 12, 0, 0)) == "off"


def test_calendar_plan_rejects_cross_client_and_revision_tampering() -> None:
    import hashlib
    import json
    import sys

    runtime_root = str(ROOT / "client/runtime")
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    from clientflow_runtime import calendar_agent

    seasons = {"2026/2027": {"2026-08-24": {"status": "off"}}}
    revision = hashlib.sha256(
        json.dumps(seasons, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {"schema_version": 1, "client_id": 7, "revision": revision, "seasons": seasons}

    try:
        calendar_agent._validate_plan(payload, client_id=8)
    except calendar_agent.CalendarPlanError:
        pass
    else:
        raise AssertionError("cross-client calendar payload blev accepteret")

    payload["revision"] = "0" * 64
    try:
        calendar_agent._validate_plan(payload, client_id=7)
    except calendar_agent.CalendarPlanError:
        pass
    else:
        raise AssertionError("tampered calendar revision blev accepteret")



def test_calendar_manual_override_is_boot_scoped_and_timestamped(tmp_path, monkeypatch) -> None:
    import sys

    runtime_root = str(ROOT / "client/runtime")
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    from clientflow_runtime import display_local_control

    state_dir = tmp_path / "display-agent"
    boot_id = tmp_path / "boot_id"
    boot_id.write_text("boot-a\n", encoding="ascii")
    monkeypatch.setattr(display_local_control, "AGENT_STATE_DIR", state_dir)
    monkeypatch.setattr(display_local_control, "CALENDAR_OVERRIDE_PATH", state_dir / "calendar-override.json")
    monkeypatch.setattr(display_local_control, "BOOT_ID_PATH", boot_id)

    display_local_control.record_calendar_manual_override("start_browser")
    created_at = display_local_control.calendar_manual_override_created_at()
    assert created_at is not None and created_at > 0
    assert display_local_control.calendar_manual_override_active() is True

    boot_id.write_text("boot-b\n", encoding="ascii")
    assert display_local_control.calendar_manual_override_active() is False
    assert not display_local_control.CALENDAR_OVERRIDE_PATH.exists()


def test_calendar_manual_override_expires_at_next_actual_schedule_boundary() -> None:
    import hashlib
    import json
    import sys
    from datetime import datetime

    runtime_root = str(ROOT / "client/runtime")
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    from clientflow_runtime import calendar_agent

    seasons = {
        "2026/2027": {
            "2026-08-24": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
            "2026-08-25": {"status": "off"},
            "2026-08-26": {"status": "on", "onTime": "09:00", "offTime": "20:00"},
        }
    }
    revision = hashlib.sha256(
        json.dumps(seasons, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    plan = calendar_agent._validate_plan(
        {"schema_version": 1, "client_id": 7, "revision": revision, "seasons": seasons},
        client_id=7,
    )

    tz = datetime.now().astimezone().tzinfo
    assert not calendar_agent._calendar_boundary_since(
        plan,
        datetime(2026, 8, 24, 10, 0, tzinfo=tz),
        datetime(2026, 8, 24, 19, 59, 59, tzinfo=tz),
    )
    assert calendar_agent._calendar_boundary_since(
        plan,
        datetime(2026, 8, 24, 10, 0, tzinfo=tz),
        datetime(2026, 8, 24, 20, 0, tzinfo=tz),
    )
    # A manual wake during an OFF day survives that day, but expires at the
    # next real ON boundary even after a Calendar service restart.
    assert not calendar_agent._calendar_boundary_since(
        plan,
        datetime(2026, 8, 25, 12, 0, tzinfo=tz),
        datetime(2026, 8, 26, 8, 59, 59, tzinfo=tz),
    )
    assert calendar_agent._calendar_boundary_since(
        plan,
        datetime(2026, 8, 25, 12, 0, tzinfo=tz),
        datetime(2026, 8, 26, 9, 0, tzinfo=tz),
    )


def test_calendar_reconcile_respects_manual_override_and_recovers_without_state_change(monkeypatch) -> None:
    import sys

    runtime_root = str(ROOT / "client/runtime")
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    from clientflow_runtime import calendar_agent

    monkeypatch.setattr(calendar_agent, "RECONCILE_SECONDS", 30.0)
    assert calendar_agent._should_enforce(
        manual_override=True,
        last_schedule_state="off",
        desired="off",
        last_enforce_at=0.0,
        now_mono=999.0,
    ) is False
    assert calendar_agent._should_enforce(
        manual_override=False,
        last_schedule_state=None,
        desired="off",
        last_enforce_at=0.0,
        now_mono=1.0,
    ) is True
    assert calendar_agent._should_enforce(
        manual_override=False,
        last_schedule_state="off",
        desired="on",
        last_enforce_at=100.0,
        now_mono=101.0,
    ) is True
    assert calendar_agent._should_enforce(
        manual_override=False,
        last_schedule_state="off",
        desired="off",
        last_enforce_at=100.0,
        now_mono=129.9,
    ) is False
    assert calendar_agent._should_enforce(
        manual_override=False,
        last_schedule_state="off",
        desired="off",
        last_enforce_at=100.0,
        now_mono=130.0,
    ) is True
