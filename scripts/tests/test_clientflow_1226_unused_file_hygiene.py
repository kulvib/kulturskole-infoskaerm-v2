from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_obsolete_bearer_release_downloader_is_absent_from_runtime_package() -> None:
    runtime = ROOT / "client/runtime/clientflow_runtime"
    assert not (runtime / "release_download.py").exists()

    system_agent = (runtime / "system_agent.py").read_text(encoding="utf-8")
    assert "release_download" not in system_agent


def test_only_runtime_consumed_config_examples_remain() -> None:
    config_dir = ROOT / "client/config-examples"
    assert {path.name for path in config_dir.iterdir() if path.is_file()} == {
        "livestream.json",
        "remote-desktop.json",
    }

    cli = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text(encoding="utf-8")
    assert 'client-runtime/config-examples/livestream.json' in cli
    assert 'client-runtime/config-examples/remote-desktop.json' in cli


def test_historical_patch_blob_inventory_is_absent() -> None:
    assert not (ROOT / "BASE_BLOBS.txt").exists()
