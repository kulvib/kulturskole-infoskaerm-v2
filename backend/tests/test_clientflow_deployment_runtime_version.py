from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from service1.routers import clientflow_deployments


def test_canonical_runtime_version_uses_fresh_status_agent_version_not_legacy_client_version(monkeypatch):
    client = SimpleNamespace(id=42, client_version="9.9.9")
    presence = SimpleNamespace(
        status=SimpleNamespace(is_online=True, agent_version="v1.3.11")
    )
    monkeypatch.setattr(clientflow_deployments, "load_client_presence", lambda *_args, **_kwargs: presence)

    assert clientflow_deployments._canonical_runtime_version(object(), client) == "1.3.11"


def test_canonical_runtime_version_fails_closed_without_fresh_online_status(monkeypatch):
    client = SimpleNamespace(id=42, client_version="1.3.10")
    presence = SimpleNamespace(
        status=SimpleNamespace(is_online=False, agent_version="1.3.11")
    )
    monkeypatch.setattr(clientflow_deployments, "load_client_presence", lambda *_args, **_kwargs: presence)

    with pytest.raises(HTTPException) as exc:
        clientflow_deployments._canonical_runtime_version(object(), client)
    assert exc.value.status_code == 409


def test_canonical_runtime_version_fails_closed_without_agent_version(monkeypatch):
    client = SimpleNamespace(id=42, client_version="1.3.10")
    presence = SimpleNamespace(
        status=SimpleNamespace(is_online=True, agent_version=None)
    )
    monkeypatch.setattr(clientflow_deployments, "load_client_presence", lambda *_args, **_kwargs: presence)

    with pytest.raises(HTTPException) as exc:
        clientflow_deployments._canonical_runtime_version(object(), client)
    assert exc.value.status_code == 409


def test_same_version_deployment_is_rejected_server_side():
    with pytest.raises(HTTPException) as exc:
        clientflow_deployments._require_version_change("1.3.11", "v1.3.11")
    assert exc.value.status_code == 409
    assert "same-version" in str(exc.value.detail)


def test_different_version_passes_server_guard():
    clientflow_deployments._require_version_change("1.3.12", "1.3.11")


class _FakeExecResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self.row = row

    def exec(self, _statement):
        return _FakeExecResult(self.row)


def test_pre_first_activation_repair_uses_server_side_claim_binding_when_status_is_offline(monkeypatch):
    client = SimpleNamespace(id=42)
    presence = SimpleNamespace(status=SimpleNamespace(is_online=False, agent_version=None))
    monkeypatch.setattr(clientflow_deployments, "load_client_presence", lambda *_args, **_kwargs: presence)
    row = SimpleNamespace(
        details={
            "fresh_install_release_id": "clientflow-1.3.17-seq-1218",
            "fresh_install_version": "1.3.17",
            "fresh_install_release_sequence": 1218,
            "fresh_install_bundle_sha256": "a" * 64,
            "fresh_install_bundle_size": 220272640,
            "fresh_install_approval_reference": "approval/1218",
            "fresh_install_candidate_sha256": "b" * 64,
            "fresh_install_source_commit": "c" * 40,
        }
    )

    binding = clientflow_deployments._pre_first_activation_repair_current(_FakeSession(row), client)

    assert binding["release_id"] == "clientflow-1.3.17-seq-1218"
    assert binding["version"] == "1.3.17"
    assert binding["release_sequence"] == 1218


def test_pre_first_activation_repair_rejects_online_status_runtime(monkeypatch):
    client = SimpleNamespace(id=42)
    presence = SimpleNamespace(status=SimpleNamespace(is_online=True, agent_version="1.3.17"))
    monkeypatch.setattr(clientflow_deployments, "load_client_presence", lambda *_args, **_kwargs: presence)

    with pytest.raises(HTTPException) as exc:
        clientflow_deployments._pre_first_activation_repair_current(_FakeSession(None), client)
    assert exc.value.status_code == 409
    assert "uden en aktiv canonical Status-runtime" in str(exc.value.detail)


def test_pre_first_activation_repair_fails_closed_without_claim_binding(monkeypatch):
    client = SimpleNamespace(id=42)
    presence = SimpleNamespace(status=SimpleNamespace(is_online=False, agent_version=None))
    monkeypatch.setattr(clientflow_deployments, "load_client_presence", lambda *_args, **_kwargs: presence)

    with pytest.raises(HTTPException) as exc:
        clientflow_deployments._pre_first_activation_repair_current(_FakeSession(None), client)
    assert exc.value.status_code == 409
    assert "claim-binding" in str(exc.value.detail)


def test_pre_first_activation_repair_target_must_be_strictly_newer_and_reasoned():
    binding = {"version": "1.3.17", "release_sequence": 1218}

    with pytest.raises(HTTPException) as exc:
        clientflow_deployments._require_pre_first_activation_repair_target(
            {"version": "1.3.17", "release_sequence": 1218},
            binding,
            reason="repair",
        )
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        clientflow_deployments._require_pre_first_activation_repair_target(
            {"version": "1.3.18", "release_sequence": 1219},
            binding,
            reason=None,
        )
    assert exc.value.status_code == 400

    clientflow_deployments._require_pre_first_activation_repair_target(
        {"version": "1.3.18", "release_sequence": 1219},
        binding,
        reason="First activation failed on the prior staged release",
    )
