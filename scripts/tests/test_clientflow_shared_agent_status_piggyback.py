from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMAND_AGENT = (ROOT / "client/runtime/clientflow_runtime/command_agent.py").read_text(encoding="utf-8")
DISPLAY_AGENT = (ROOT / "client/runtime/clientflow_runtime/display_agent.py").read_text(encoding="utf-8")
SYSTEM_AGENT = (ROOT / "client/runtime/clientflow_runtime/system_agent.py").read_text(encoding="utf-8")
LIVESTREAM_AGENT = (ROOT / "client/runtime/clientflow_runtime/livestream_agent.py").read_text(encoding="utf-8")
STATUS = (ROOT / "client/runtime/clientflow_runtime/status.py").read_text(encoding="utf-8")
ROUTER = (ROOT / "backend/service1/routers/shared_domain.py").read_text(encoding="utf-8")


def test_display_and_system_piggyback_due_status_on_existing_claim_request():
    assert "piggyback_status_on_claim=True" in DISPLAY_AGENT
    assert "piggyback_status_on_claim=True" in SYSTEM_AGENT
    assert "piggyback_status_on_claim=True" not in LIVESTREAM_AGENT
    assert 'body["status_report"] = status_report' in COMMAND_AGENT
    assert "if piggybacked_status is not None:" in COMMAND_AGENT
    assert 'payload.get("status_reported") is True' in COMMAND_AGENT
    assert "self._last_status = time.monotonic()" in COMMAND_AGENT
    assert "self._report_status_if_due(force=True)" in COMMAND_AGENT


def test_piggyback_uses_exact_same_canonical_status_payload_builder():
    assert "def build_status_body(" in STATUS
    assert "json_body=build_status_body(observed_state=observed_state, payload=payload)" in STATUS
    assert "piggybacked_status = build_status_body(" in COMMAND_AGENT


def test_backend_claim_keeps_legacy_body_compatible_and_status_optional():
    assert "status_report: StatusBody | None = None" in ROUTER
    assert "if body.status_report is None:" in ROUTER
    assert "require_shared_agent_token(" in ROUTER
    assert "require_shared_agent_context(" in ROUTER
    assert "body=body.status_report" in ROUTER
    assert "payload = claim_shared_command" in ROUTER
    assert 'payload["status_reported"] = True' in ROUTER



def test_queue_agent_sends_due_status_inside_claim_without_separate_status_request(monkeypatch):
    from types import SimpleNamespace
    from clientflow_runtime import command_agent as module

    class FakeTransport:
        def __init__(self):
            self.credential = SimpleNamespace(
                client_id=17,
                domain=SimpleNamespace(value="display"),
            )
            self.requests = []

        def json_request(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            if method == "POST" and path.endswith("/commands/claim"):
                return {"claimed": None, "status_reported": True}
            return {"ok": True}

    transport = FakeTransport()
    agent = module.QueueAgent(
        transport,
        lambda _context: {},
        status_payload=lambda: {"runtime": {"state": "running"}},
        piggyback_status_on_claim=True,
    )

    def stop_after_first_idle(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(module.time, "sleep", stop_after_first_idle)
    agent.run_forever()

    assert len(transport.requests) == 1
    method, path, kwargs = transport.requests[0]
    assert method == "POST"
    assert path == "/api/display-agent/clients/17/commands/claim"
    body = kwargs["json_body"]
    assert body["lease_seconds"] == 60
    assert body["status_report"]["observed_state"] == "online"
    assert body["status_report"]["status_payload"] == {"runtime": {"state": "running"}}
    assert body["status_report"]["schema_version"] == 1



def test_queue_agent_falls_back_to_standalone_status_when_backend_does_not_ack_piggyback(monkeypatch):
    from types import SimpleNamespace
    from clientflow_runtime import command_agent as module

    class LegacyBackendTransport:
        def __init__(self):
            self.credential = SimpleNamespace(
                client_id=18,
                domain=SimpleNamespace(value="system"),
            )
            self.requests = []

        def json_request(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            if method == "POST" and path.endswith("/commands/claim"):
                # Older backend accepted the request body but ignored the unknown
                # status_report field, so no explicit status_reported ACK exists.
                return {"claimed": None}
            if method == "PUT" and path.endswith("/status"):
                return {"ok": True}
            raise AssertionError((method, path))

    transport = LegacyBackendTransport()
    agent = module.QueueAgent(
        transport,
        lambda _context: {},
        status_payload=lambda: {"broker_socket": True},
        piggyback_status_on_claim=True,
    )

    def stop_after_first_idle(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(module.time, "sleep", stop_after_first_idle)
    agent.run_forever()

    assert [request[0] for request in transport.requests] == ["POST", "PUT"]
    assert transport.requests[0][1] == "/api/system-agent/clients/18/commands/claim"
    assert transport.requests[1][1] == "/api/system-agent/clients/18/status"
