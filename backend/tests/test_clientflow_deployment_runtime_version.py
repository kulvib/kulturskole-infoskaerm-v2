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
