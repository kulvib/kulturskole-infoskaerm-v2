"""Remote Desktop file channel restricted to one dedicated transfer root."""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from typing import Any, Iterator

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_CHUNK_BYTES = 768 * 1024
MAX_LIST_ENTRIES = 500
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _safe_identifier(value: object, *, name: str) -> str:
    result = str(value or "")
    if not _IDENTIFIER_PATTERN.fullmatch(result):
        raise ValueError(f"{name} er ugyldig")
    return result


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_private_directory(path: Path, *, create_parents: bool) -> None:
    try:
        path.mkdir(mode=0o700, parents=create_parents, exist_ok=True)
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError(f"Remote Desktop-katalog kunne ikke oprettes sikkert: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"Remote Desktop-katalog er ikke en almindelig mappe: {path}")
    if metadata.st_mode & 0o077:
        os.chmod(path, 0o700)
        metadata = path.lstat()
        if metadata.st_mode & 0o077:
            raise ValueError(f"Remote Desktop-katalog har for brede rettigheder: {path}")


class FileArea:
    def __init__(self, root: Path, staging_root: Path | None = None) -> None:
        self.root = root
        self.staging_root = staging_root or root.parent / "uploads"
        _ensure_private_directory(self.root, create_parents=True)
        _ensure_private_directory(self.staging_root, create_parents=True)
        self.uploads: dict[tuple[str, str], dict[str, Any]] = {}

    def _parts(self, raw: object) -> tuple[str, ...]:
        value = str(raw or "").replace("\\", "/").strip("/")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            if value:
                raise ValueError("Filstien er ugyldig")
            return ()
        return path.parts

    def _resolve(self, raw: object, *, must_exist: bool = True) -> Path:
        parts = self._parts(raw)
        candidate = self.root.joinpath(*parts)
        root_resolved = self.root.resolve()
        if must_exist:
            resolved = candidate.resolve(strict=True)
        else:
            parent = candidate.parent.resolve(strict=True)
            resolved = parent / candidate.name
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise ValueError("Filstien forlader Remote Desktop-filområdet")
        current = self.root
        for part in parts[:-1] if not must_exist else parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Symlinks er ikke tilladt i Remote Desktop-filområdet")
        return resolved

    def list(self, relative: object) -> dict[str, Any]:
        directory = self._resolve(relative)
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("Stien er ikke en mappe")
        entries = []
        for item in sorted(directory.iterdir(), key=lambda value: (not value.is_dir(), value.name.casefold())):
            if len(entries) >= MAX_LIST_ENTRIES:
                break
            if item.is_symlink():
                continue
            stat = item.stat()
            entries.append(
                {
                    "name": item.name,
                    "path": item.relative_to(self.root).as_posix(),
                    "type": "directory" if item.is_dir() else "file",
                    "size_bytes": stat.st_size if item.is_file() else None,
                    "modified_at": stat.st_mtime,
                }
            )
        return {
            "path": directory.relative_to(self.root).as_posix(),
            "entries": entries,
            "truncated": len(entries) >= MAX_LIST_ENTRIES,
        }

    def download_messages(
        self,
        session_id: str,
        transfer_id: str,
        relative: object,
    ) -> Iterator[dict[str, Any]]:
        session_id = _safe_identifier(session_id, name="session_id")
        transfer_id = _safe_identifier(transfer_id, name="transfer_id")
        path = self._resolve(relative)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("Filen findes ikke")
            size = metadata.st_size
            if size > MAX_FILE_BYTES:
                raise ValueError("Filen er for stor")
            yield {
                "type": "file_download_offer",
                "session_id": session_id,
                "transfer_id": transfer_id,
                "path": path.relative_to(self.root).as_posix(),
                "size_bytes": size,
            }
            digest = hashlib.sha256()
            offset = 0
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                while chunk := handle.read(MAX_CHUNK_BYTES):
                    digest.update(chunk)
                    yield {
                        "type": "file_download_chunk",
                        "session_id": session_id,
                        "transfer_id": transfer_id,
                        "offset": offset,
                        "data": base64.b64encode(chunk).decode("ascii"),
                        "encoding": "base64",
                    }
                    offset += len(chunk)
        finally:
            os.close(descriptor)
        yield {
            "type": "file_download_complete",
            "session_id": session_id,
            "transfer_id": transfer_id,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }

    def upload_offer(self, session_id: str, message: dict[str, Any]) -> dict[str, Any]:
        session_id = _safe_identifier(session_id, name="session_id")
        transfer_id = _safe_identifier(message.get("transfer_id"), name="transfer_id")
        target = self._resolve(message.get("path"), must_exist=False)
        if target.exists() or target.is_symlink():
            raise ValueError("Uploadmålet findes allerede")
        size = int(message.get("size_bytes", -1))
        sha256 = str(message.get("sha256") or "")
        if not 0 <= size <= MAX_FILE_BYTES or not _SHA256_PATTERN.fullmatch(sha256):
            raise ValueError("Uploadmetadata er ugyldig")
        key = (session_id, transfer_id)
        if key in self.uploads:
            raise ValueError("Uploaden er allerede tilbudt")
        temporary = self.staging_root / session_id / f"{transfer_id}.part"
        _ensure_private_directory(temporary.parent, create_parents=False)
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("Uploadens stagingfil findes allerede")
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        self.uploads[key] = {
            "target_relative": target.relative_to(self.root).as_posix(),
            "temporary": temporary,
            "size": size,
            "sha256": sha256,
            "received": 0,
        }
        return {"accepted": True, "transfer_id": transfer_id}

    def upload_chunk(self, session_id: str, message: dict[str, Any]) -> dict[str, Any]:
        session_id = _safe_identifier(session_id, name="session_id")
        transfer_id = _safe_identifier(message.get("transfer_id"), name="transfer_id")
        state = self.uploads.get((session_id, transfer_id))
        if state is None:
            raise ValueError("Uploaden er ikke tilbudt")
        offset = int(message.get("offset", -1))
        if offset != state["received"]:
            raise ValueError("Uploadchunk har forkert offset")
        try:
            payload = base64.b64decode(str(message.get("data") or ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Uploadchunk er ikke gyldig base64") from exc
        if not payload or len(payload) > MAX_CHUNK_BYTES or state["received"] + len(payload) > state["size"]:
            raise ValueError("Uploadchunk er ugyldig")
        descriptor = os.open(state["temporary"], os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("Uploadchunk kunne ikke skrives")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        state["received"] += len(payload)
        return {"accepted": True, "transfer_id": transfer_id, "received": state["received"]}

    def upload_complete(self, session_id: str, message: dict[str, Any]) -> dict[str, Any]:
        session_id = _safe_identifier(session_id, name="session_id")
        transfer_id = _safe_identifier(message.get("transfer_id"), name="transfer_id")
        state = self.uploads.pop((session_id, transfer_id), None)
        if state is None:
            raise ValueError("Uploaden er ikke tilbudt")
        temporary: Path = state["temporary"]
        try:
            digest = hashlib.sha256()
            size = 0
            descriptor = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                while chunk := handle.read(MAX_CHUNK_BYTES):
                    size += len(chunk)
                    digest.update(chunk)
            if size != state["size"] or digest.hexdigest() != state["sha256"]:
                raise ValueError("Uploadens størrelse eller SHA-256 matcher ikke")
            target = self._resolve(state["target_relative"], must_exist=False)
            if target.exists() or target.is_symlink():
                raise ValueError("Uploadmålet findes allerede")
            os.link(temporary, target, follow_symlinks=False)
            os.chmod(target, 0o600)
            _fsync_directory(target.parent)
            temporary.unlink()
            _fsync_directory(temporary.parent)
            return {
                "accepted": True,
                "transfer_id": transfer_id,
                "path": target.relative_to(self.root).as_posix(),
                "size_bytes": size,
                "sha256": state["sha256"],
            }
        finally:
            temporary.unlink(missing_ok=True)

    def operation(self, message_type: str, message: dict[str, Any]) -> dict[str, Any]:
        if message_type == "file_delete_request":
            target = self._resolve(message.get("path"))
            if target == self.root:
                raise ValueError("Filområdets rod kan ikke slettes")
            parent = target.parent
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            _fsync_directory(parent)
            return {"operation": "delete", "path": str(message.get("path") or "")}
        if message_type == "file_mkdir_request":
            target = self._resolve(message.get("path"), must_exist=False)
            if target.exists() or target.is_symlink():
                raise ValueError("Mappen findes allerede")
            target.mkdir(mode=0o700, parents=False, exist_ok=False)
            _fsync_directory(target.parent)
            return {"operation": "mkdir", "path": target.relative_to(self.root).as_posix()}
        if message_type in {"file_rename_request", "file_move_request"}:
            source = self._resolve(message.get("path") or message.get("source"))
            destination = self._resolve(message.get("new_path") or message.get("destination"), must_exist=False)
            if source == self.root:
                raise ValueError("Filområdets rod kan ikke flyttes")
            if destination.exists() or destination.is_symlink():
                raise ValueError("Destinationen findes allerede")
            source_parent = source.parent
            source.rename(destination)
            _fsync_directory(source_parent)
            if destination.parent != source_parent:
                _fsync_directory(destination.parent)
            return {
                "operation": "rename" if message_type == "file_rename_request" else "move",
                "path": destination.relative_to(self.root).as_posix(),
            }
        raise ValueError("Ukendt filoperation")

    def close_session(self, session_id: str) -> None:
        session_id = _safe_identifier(session_id, name="session_id")
        for key, state in list(self.uploads.items()):
            if key[0] == session_id:
                state["temporary"].unlink(missing_ok=True)
                self.uploads.pop(key, None)
        staging = self.staging_root / session_id
        try:
            staging.rmdir()
        except OSError:
            pass
