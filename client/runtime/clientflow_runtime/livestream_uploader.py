"""Generation-aware HLS uploader. Stale generations are rejected by the backend."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any
import uuid
from urllib.parse import quote

from .atomic import atomic_write_json
from .config import DomainCredential
from .constants import Domain
from .livestream_paths import DESIRED_PATH, GENERATIONS_DIR, UPLOADER_STATUS_PATH
from .logging_utils import configure_logging
from .net import DomainTransport, TransportError, backoff_seconds

_SEGMENT_PATTERN = re.compile(r"^segment-(\d{9})\.(?:ts|m4s)$")


class SegmentVanishedError(RuntimeError):
    """A rolling HLS segment disappeared between directory scan and open()."""


def _canonical_generation(value: object) -> str:
    raw = str(value or "")
    try:
        parsed = uuid.UUID(raw)
    except ValueError as exc:
        raise RuntimeError("Livestream desired state har ugyldig generation") from exc
    canonical = str(parsed)
    if raw != canonical:
        raise RuntimeError("Livestreamgeneration skal være en kanonisk UUID")
    return canonical


def _read_regular_file(path: Path, *, max_bytes: int = 64 * 1024 * 1024) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        if _SEGMENT_PATTERN.match(path.name):
            raise SegmentVanishedError("Rullende HLS-segment forsvandt før upload") from exc
        raise RuntimeError("Livestreamfil kunne ikke åbnes sikkert") from exc
    except OSError as exc:
        raise RuntimeError("Livestreamfil kunne ikke åbnes sikkert") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            raise RuntimeError("Livestreamfil er ugyldig eller for stor")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise RuntimeError("Livestreamfil er større end uploadkontrakten tillader")
        return payload
    finally:
        os.close(descriptor)


class Uploader:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.livestream.uploader")
        self.credential = DomainCredential.load(Domain.LIVESTREAM)
        self.transport = DomainTransport(self.credential)
        self.uploaded: dict[tuple[str, str], str] = {}

    def _read_desired(self) -> dict[str, Any]:
        try:
            value = json.loads(DESIRED_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Livestream desired state er ugyldig") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Livestream desired state skal være et objekt")
        if value and value.get("schema_version") != 1:
            raise RuntimeError("Livestream desired state mangler schema_version 1")
        desired = value.get("desired")
        if desired not in {None, "running", "stopped"}:
            raise RuntimeError("Livestream desired state er ugyldig")
        generation = value.get("generation_id")
        if generation is not None:
            value = dict(value)
            value["generation_id"] = _canonical_generation(generation)
        return value

    def _sequence(self, generation_id: str, filename: str) -> int:
        match = _SEGMENT_PATTERN.match(filename)
        if match:
            return int(match.group(1))
        segment_sequences: list[int] = []
        for uploaded_generation, uploaded_filename in self.uploaded:
            if uploaded_generation != generation_id:
                continue
            uploaded_match = _SEGMENT_PATTERN.match(uploaded_filename)
            if uploaded_match:
                segment_sequences.append(int(uploaded_match.group(1)))
        return max(segment_sequences, default=0)

    def _upload(self, generation_id: str, path: Path) -> None:
        payload = _read_regular_file(path)
        sha256 = hashlib.sha256(payload).hexdigest()
        key = (generation_id, path.name)
        if self.uploaded.get(key) == sha256:
            return
        sequence = self._sequence(generation_id, path.name)
        client_id = self.credential.client_id
        filename = quote(path.name, safe="")
        content_type = {
            ".m3u8": "application/vnd.apple.mpegurl",
            ".ts": "video/mp2t",
            ".m4s": "video/iso.segment",
            ".mp4": "video/mp4",
        }[path.suffix.lower()]
        self.transport.request(
            "PUT",
            f"/api/livestream-agent/clients/{client_id}/generations/{generation_id}/files/{filename}?sequence={sequence}&sha256={sha256}",
            data=payload,
            headers={"Content-Type": content_type},
            expected=(200,),
            timeout=60,
        )
        self.uploaded[key] = sha256

    @property
    def current_generation(self) -> str:
        desired = self._read_desired()
        return str(desired.get("generation_id") or "")

    def _status(self, state: str, **details: Any) -> None:
        payload = {
            "schema_version": 1,
            "state": state,
            "generation_id": self.current_generation or None,
            "uploaded_files": len(self.uploaded),
            "updated_at": time.time(),
            **details,
        }
        atomic_write_json(UPLOADER_STATUS_PATH, payload, mode=0o640)

    def run(self) -> int:
        attempt = 0
        while True:
            try:
                desired = self._read_desired()
                generation = str(desired.get("generation_id") or "")
                if generation:
                    self.uploaded = {key: value for key, value in self.uploaded.items() if key[0] == generation}
                if desired.get("desired") != "running" or not generation:
                    self._status("idle")
                    attempt = 0
                    time.sleep(1)
                    continue
                output = GENERATIONS_DIR / generation / "out"
                if output.is_dir():
                    files = sorted(
                        (item for item in output.iterdir() if not item.is_symlink() and item.is_file()),
                        key=lambda item: (item.suffix == ".m3u8", item.name),
                    )
                    for path in files:
                        if path.suffix.lower() not in {".m3u8", ".ts", ".m4s", ".mp4"}:
                            continue
                        try:
                            self._upload(generation, path)
                        except SegmentVanishedError:
                            # hlssink deletes old rolling segments asynchronously.
                            # Re-scan instead of degrading the whole uploader.
                            continue
                self._status("uploading")
                attempt = 0
                time.sleep(0.5)
            except KeyboardInterrupt:
                return 0
            except TransportError as exc:
                if exc.status_code == 409:
                    self._status("stale_generation", error=str(exc))
                    time.sleep(5)
                    continue
                self.logger.exception("upload_failed")
                self._status("degraded", error=str(exc)[:1000])
                time.sleep(backoff_seconds(attempt))
                attempt += 1
            except Exception as exc:
                self.logger.exception("uploader_failed")
                try:
                    self._status("failed", error=str(exc)[:1000])
                except Exception:
                    pass
                time.sleep(backoff_seconds(attempt))
                attempt += 1


def main() -> int:
    return Uploader().run()
