from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def _calendar_agent():
    import sys
    runtime_root = str(ROOT / "client/runtime")
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    from clientflow_runtime import calendar_agent
    return calendar_agent


def _payload(client_id: int = 7):
    seasons = {"2026/2027": {"2026-09-22": {"status": "off"}}}
    revision = hashlib.sha256(
        json.dumps(seasons, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"schema_version": 1, "client_id": client_id, "revision": revision, "seasons": seasons}


class _Response:
    def __init__(self, status_code: int, payload=None, *, etag: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {"etag": etag} if etag else {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Transport:
    def __init__(self, responses):
        self.credential = SimpleNamespace(client_id=7)
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.responses.pop(0)


def test_conditional_calendar_304_reuses_validated_cache_without_write(tmp_path, monkeypatch):
    agent = _calendar_agent()
    cache = tmp_path / "schedule.json"
    monkeypatch.setattr(agent, "CACHE_PATH", cache)
    current = agent._validate_plan(_payload(), client_id=7)
    cache.write_text(json.dumps(current), encoding="utf-8")
    before = cache.read_bytes()
    transport = _Transport([_Response(304, etag='"cfcal-same"')])

    plan, etag, changed = agent._fetch_plan_conditional(
        transport,
        current_plan=current,
        etag='"cfcal-same"',
    )

    assert plan == current
    assert etag == '"cfcal-same"'
    assert changed is False
    assert cache.read_bytes() == before
    assert transport.calls[0][2]["headers"] == {"If-None-Match": '"cfcal-same"'}
    assert transport.calls[0][2]["expected"] == (200, 304)


def test_conditional_calendar_200_validates_and_replaces_cache(tmp_path, monkeypatch):
    agent = _calendar_agent()
    monkeypatch.setattr(agent, "CACHE_PATH", tmp_path / "schedule.json")
    payload = _payload()
    transport = _Transport([_Response(200, payload, etag='"cfcal-new"')])

    plan, etag, changed = agent._fetch_plan_conditional(
        transport,
        current_plan=None,
        etag=None,
    )

    assert plan["revision"] == payload["revision"]
    assert etag == '"cfcal-new"'
    assert changed is True
    assert json.loads(agent.CACHE_PATH.read_text(encoding="utf-8")) == plan
    assert transport.calls[0][2]["headers"] is None


def test_304_without_local_cache_fails_closed():
    agent = _calendar_agent()
    transport = _Transport([_Response(304, etag='"cfcal-same"')])
    try:
        agent._fetch_plan_conditional(transport, current_plan=None, etag='"cfcal-same"')
    except agent.CalendarPlanError:
        pass
    else:
        raise AssertionError("304 without local Calendar cache was accepted")
