"""Output-only session transcript with explicit hashes and permissions."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import threading


class OutputTranscript:
    def __init__(self, directory: Path, session_id: str) -> None:
        safe_id = "".join(char for char in session_id if char.isalnum() or char in "-_")
        if not safe_id or safe_id != session_id:
            raise ValueError("Ugyldigt transcript session-id")
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        self.path = directory / f"{safe_id}.output.log"
        self._handle = self.path.open("xb", buffering=0)
        os.chmod(self.path, 0o600)
        self._hash = hashlib.sha256()
        self._lock = threading.Lock()
        header = (
            f"ClientFlow output-only transcript\n"
            f"session_id={session_id}\n"
            f"started_at={datetime.now(timezone.utc).isoformat()}\n\n"
        ).encode("utf-8")
        self.append(header)

    def append(self, payload: bytes) -> None:
        if not payload:
            return
        with self._lock:
            self._handle.write(payload)
            self._hash.update(payload)

    def close(self) -> tuple[str, str]:
        with self._lock:
            if not self._handle.closed:
                self._handle.flush()
                os.fsync(self._handle.fileno())
                self._handle.close()
            return str(self.path), self._hash.hexdigest()
