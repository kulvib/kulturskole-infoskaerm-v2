from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "client/legacy-client-parity.json"
GATE = ROOT / "scripts/verify_clientflow_legacy119_capability_gate.py"


def _gate_module():
    spec = importlib.util.spec_from_file_location("clientflow_legacy119_capability_gate", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_119_exact_installer_and_166_file_payload_are_fully_disposed() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    baseline = payload["legacy_baseline"]
    assert payload["schema_version"] == 2
    assert baseline == {
        "release": "1.1.19",
        "sequence": 1119,
        "installer_zip_sha256": "61dc8a417aaa32f4eabc7430a2af886933473142cebcdcbe8f1064a318941e80",
        "installer_zip_size": 528568,
        "payload_tar_sha256": "d490dd8f0effccc58e8d5687ae95d0821bf2747d4f131a2ee3a9c3088c1ec331",
        "payload_tar_size": 482779,
        "payload_file_count": 166,
        "installer_surface_file_count": 11,
        "total_inventory_count": 177,
        "inventory_sha256": "e542df2c1c3d9b6c4a88966803bb6f39c6a938744756e6202eb9abde83a8d695",
    }
    inventory = payload["inventory"]
    assert len(inventory) == 177
    assert sum(row["surface"] == "payload" for row in inventory) == 166
    assert sum(row["surface"] == "installer" for row in inventory) == 11
    assert len({(row["surface"], row["path"]) for row in inventory}) == 177


def test_every_legacy_capability_has_real_v2_replacement_and_executable_proof() -> None:
    module = _gate_module()
    summary = module._validate(ROOT)
    assert summary["inventory_entries"] == 177
    assert summary["capabilities"] == 13
    assert summary["capabilities_with_executable_proof"] == 13
    assert summary["python_proof_files"] >= 10
    assert summary["frontend_proof_files"] >= 5
    assert summary["host_proof_files"] >= 2


def test_frozen_domains_are_explicitly_read_only_capabilities() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in payload["capabilities"]}
    assert {cap_id for cap_id, row in by_id.items() if row["frozen"]} == {
        "frozen_livestream",
        "frozen_terminal",
        "frozen_remote_desktop",
    }
    for cap_id in ("frozen_livestream", "frozen_terminal", "frozen_remote_desktop"):
        assert by_id[cap_id]["status"] == "implemented"
        assert any(proof["proof_class"] != "source_contract" for proof in by_id[cap_id]["proofs"])


def test_old_46_python_file_gate_is_no_longer_the_acceptance_boundary() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, sort_keys=True)
    assert "payload_python_file_count" not in serialized
    assert payload["legacy_baseline"]["payload_file_count"] == 166
    assert payload["legacy_baseline"]["total_inventory_count"] == 177
