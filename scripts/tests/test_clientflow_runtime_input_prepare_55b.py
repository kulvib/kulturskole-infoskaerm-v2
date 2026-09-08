from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    path = ROOT / "scripts/prepare_clientflow_runtime_input_transport.py"
    spec = importlib.util.spec_from_file_location("runtime_input_prepare_55b", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lock(tmp_path: Path, *, runtime: bytes = b"runtime", wheel: bytes = b"wheel", platform: bytes = b"new-platform", bootstrap: bytes = b"bootstrap"):
    rows = {
        "python-runtime-amd64.tar": runtime,
        "wheel.whl": wheel,
    }
    lock = {
        "schema_version": 1,
        "runtime_python": "3.13.14",
        "architecture": "amd64",
        "artifacts": [
            {"file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in rows.items()
        ],
        "platform_artifacts": [
            {
                "file": "chrome.deb",
                "package": "google-chrome-stable",
                "version": "152.0.0-1",
                "architecture": "amd64",
                "size": len(platform),
                "sha256": hashlib.sha256(platform).hexdigest(),
            }
        ],
        "preclaim_bootstrap_artifacts": [
            {
                "file": "apt.deb",
                "package": "apt",
                "version": "1",
                "architecture": "amd64",
                "size": len(bootstrap),
                "sha256": hashlib.sha256(bootstrap).hexdigest(),
            }
        ],
    }
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path, {**rows, "chrome.deb": platform, "apt.deb": bootstrap}


def _base_tar(tmp_path: Path, contents: dict[str, bytes], *, runtime_override: bytes | None = None) -> Path:
    path = tmp_path / "base.tar"
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as tf:
        for directory in ("wheelhouse", "platform", "bootstrap"):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o700
            tf.addfile(info)
        members = {
            "python-runtime-amd64.tar": runtime_override if runtime_override is not None else contents["python-runtime-amd64.tar"],
            "wheelhouse/wheel.whl": contents["wheel.whl"],
            "platform/old-chrome.deb": b"old-platform-is-not-reused",
            "bootstrap/apt.deb": contents["apt.deb"],
        }
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o400
            import io
            tf.addfile(info, io.BytesIO(data))
    return path


def test_seed_reuses_only_current_runtime_and_bootstrap_bytes_and_ignores_old_platform(tmp_path: Path):
    module = _load_module()
    lock, contents = _lock(tmp_path)
    base = _base_tar(tmp_path, contents)
    source = tmp_path / "source"
    module.seed_reusable_inputs(base, source, lock)
    assert (source / "python-runtime-amd64.tar").read_bytes() == contents["python-runtime-amd64.tar"]
    assert (source / "wheelhouse/wheel.whl").read_bytes() == contents["wheel.whl"]
    assert (source / "bootstrap/apt.deb").read_bytes() == contents["apt.deb"]
    assert list((source / "platform").iterdir()) == []


def test_seed_fails_closed_on_tampered_reusable_byte(tmp_path: Path):
    module = _load_module()
    lock, contents = _lock(tmp_path)
    base = _base_tar(tmp_path, contents, runtime_override=b"tampered")
    with pytest.raises(ValueError, match="size mismatch|SHA-256 mismatch"):
        module.seed_reusable_inputs(base, tmp_path / "source", lock)


def test_platform_url_set_must_match_current_lock_exactly(tmp_path: Path):
    module = _load_module()
    lock, _ = _lock(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "platform").mkdir()
    with pytest.raises(ValueError, match="does not match lock"):
        module.fetch_platform_inputs(source, lock, {})
    with pytest.raises(ValueError, match="does not match lock"):
        module.fetch_platform_inputs(source, lock, {"chrome.deb": "https://example.invalid/chrome", "extra.deb": "https://example.invalid/extra"})


def test_prepare_transport_builds_twice_and_publishes_verified_bytes(tmp_path: Path, monkeypatch):
    module = _load_module()
    lock, contents = _lock(tmp_path)
    base = _base_tar(tmp_path, contents)

    def fake_fetch(url, target, *, expected_size, expected_sha256):
        assert url == "https://example.invalid/chrome.deb"
        data = contents["chrome.deb"]
        assert len(data) == expected_size
        assert hashlib.sha256(data).hexdigest() == expected_sha256
        target.write_bytes(data)

    monkeypatch.setattr(module, "_fetch_exact", fake_fetch)
    output = tmp_path / "runtime-inputs.tar"
    size, digest = module.prepare_transport(
        base_archive=base,
        lock_path=lock,
        platform_urls={"chrome.deb": "https://example.invalid/chrome.deb"},
        output=output,
    )
    assert output.stat().st_size == size
    assert hashlib.sha256(output.read_bytes()).hexdigest() == digest
    materializer = module._load_script("verify_prepare_test", "materialize_clientflow_runtime_inputs.py")
    result = materializer.materialize(output, tmp_path / "materialized", lock)
    assert {x["file"] for x in result["platform_artifacts"]} == {"chrome.deb"}


def test_github_workflow_is_manual_exact_source_no_replace_transport_only():
    workflow = (ROOT / ".github/workflows/runtime-input-transport.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "ref: ${{ inputs.expected_source_sha }}" in workflow
    assert "verify_github_ci_run.py" in workflow
    assert "--head-branch main" in workflow
    assert "source release sequence is not staged ahead of catalog" in workflow
    assert "gh release view \"$TAG\"" in workflow
    assert "gh release create \"$TAG\"" in workflow
    assert "--prerelease" in workflow
    assert "Transport only. Not release authority." in workflow
    assert "RUNTIME_INPUT_TRANSPORT_READY=PASS" in workflow
    forbidden = ["release-approve", "clientflow_release_catalog.json >", "latest_stable", "default_install_version="]
    for token in forbidden:
        assert token not in workflow
