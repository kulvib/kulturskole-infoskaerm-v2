from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "client/runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from clientflow_runtime import remote_desktop_files as files_module  # noqa: E402


def test_upload_publish_never_links_private_staging_across_filesystems(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "kiosk-home"
    staging = tmp_path / "private-staging"
    target_dir = root / "Billeder" / "Skærmbilleder"
    target_dir.mkdir(parents=True)
    root.chmod(0o755)

    area = files_module.FileArea(root, staging)
    session_id = "session-1"
    transfer_id = "transfer-1"
    payload = b"physical-acceptance-upload" * 256
    digest = hashlib.sha256(payload).hexdigest()
    relative = "Billeder/Skærmbilleder/worklog-planiq-main.zip"

    area.upload_offer(session_id, {
        "transfer_id": transfer_id,
        "path": relative,
        "size_bytes": len(payload),
        "sha256": digest,
    })
    area.upload_chunk(session_id, {
        "transfer_id": transfer_id,
        "offset": 0,
        "data": base64.b64encode(payload).decode("ascii"),
    })

    real_link = files_module.os.link
    observed_links: list[tuple[Path, Path]] = []

    def guarded_link(src, dst, **kwargs):
        source = Path(src)
        destination = Path(dst)
        observed_links.append((source, destination))
        # This is the regression contract: publishing is only allowed from a
        # target-local temporary file, never directly from /var/lib staging.
        assert source.parent == destination.parent
        assert staging not in source.parents
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(files_module.os, "link", guarded_link)
    result = area.upload_complete(session_id, {"transfer_id": transfer_id})

    target = root / relative
    assert result["accepted"] is True
    assert result["sha256"] == digest
    assert target.read_bytes() == payload
    assert (target.stat().st_mode & 0o777) == 0o600
    assert len(observed_links) == 1
    assert not any(staging.rglob("*.part"))


def test_upload_publish_refuses_target_race_and_cleans_temporary_files(tmp_path: Path) -> None:
    root = tmp_path / "kiosk-home"
    staging = tmp_path / "private-staging"
    root.mkdir()
    root.chmod(0o755)
    area = files_module.FileArea(root, staging)
    payload = b"race-safe"
    digest = hashlib.sha256(payload).hexdigest()

    area.upload_offer("session-2", {
        "transfer_id": "transfer-2",
        "path": "target.txt",
        "size_bytes": len(payload),
        "sha256": digest,
    })
    area.upload_chunk("session-2", {
        "transfer_id": "transfer-2",
        "offset": 0,
        "data": base64.b64encode(payload).decode("ascii"),
    })
    (root / "target.txt").write_text("existing", encoding="utf-8")

    with pytest.raises(ValueError, match="Uploadmålet findes allerede"):
        area.upload_complete("session-2", {"transfer_id": "transfer-2"})

    assert (root / "target.txt").read_text(encoding="utf-8") == "existing"
    assert not list(root.glob(".clientflow-upload-*.part"))
    assert not any(staging.rglob("*.part"))
