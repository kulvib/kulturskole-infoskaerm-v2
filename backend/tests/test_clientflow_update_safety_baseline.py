from __future__ import annotations

import json
from pathlib import Path

import pytest

from service1 import clientflow_releases
from service1.clientflow_releases import ClientFlowCatalogError


ROOT = Path(__file__).resolve().parents[2]
CURRENT_CATALOG = ROOT / "backend/service1/clientflow_release_catalog.json"


def _future_catalog(*, minimum_current: str) -> dict:
    data = json.loads(CURRENT_CATALOG.read_text(encoding="utf-8"))
    release = dict(data["releases"][0])
    release.update(
        {
            "version": "1.3.11",
            "client_version": "1.3.11",
            "release_sequence": 1212,
            "revision": "clientflow-1.3.11-seq-1212",
            "release_id": "clientflow-1.3.11-seq-1212",
            "min_current_version": minimum_current,
        }
    )
    data.update(
        {
            "catalog_sequence": 1212,
            "latest_stable": "1.3.11",
            "default_install_version": "1.3.11",
            "releases": [release],
        }
    )
    return data


def _load_temp_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data: dict):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(clientflow_releases, "CATALOG_PATH", path)
    clientflow_releases.load_catalog.cache_clear()
    try:
        return clientflow_releases.load_catalog()
    finally:
        clientflow_releases.load_catalog.cache_clear()


def test_post_1211_release_cannot_advertise_1310_as_in_place_update_source(monkeypatch, tmp_path):
    with pytest.raises(ClientFlowCatalogError, match="sikre ClientFlow 1.3.11-baseline"):
        _load_temp_catalog(monkeypatch, tmp_path, _future_catalog(minimum_current="1.3.10"))


def test_1311_fresh_baseline_can_be_published_but_rejects_1310_for_in_place_update(monkeypatch, tmp_path):
    catalog = _load_temp_catalog(monkeypatch, tmp_path, _future_catalog(minimum_current="1.3.11"))
    release = catalog["releases"][0]

    # Fresh-install selection does not need a predecessor. The same catalog
    # entry may still describe the in-place contract for later safe baselines.
    assert "fresh_install" in release["install_modes"]
    assert release["min_current_version"] == "1.3.11"

    with pytest.raises(ClientFlowCatalogError, match="kræver mindst ClientFlow 1.3.11"):
        clientflow_releases.validate_release_compatibility(
            release,
            current_version="1.3.10",
            ubuntu_version="26.04",
        )

    clientflow_releases.validate_release_compatibility(
        release,
        current_version="1.3.11",
        ubuntu_version="26.04",
    )
