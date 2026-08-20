from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

from .constants import (
    MAX_BUNDLE_BYTES,
    MAX_FRESH_INSTALLER_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_MEMBER_BYTES,
    MAX_PATH_LENGTH,
    MAX_PAYLOAD_BYTES,
    MAX_PAYLOAD_FILES,
)


class ArchiveError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_files: int = MAX_PAYLOAD_FILES
    max_total_bytes: int = MAX_PAYLOAD_BYTES
    max_member_bytes: int = MAX_MEMBER_BYTES
    max_path_length: int = MAX_PATH_LENGTH


def validate_member_name(name: str, *, expected_root: str | None = None) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name or len(name) > MAX_PATH_LENGTH:
        raise ArchiveError("Arkivet indeholder et ugyldigt filnavn")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ArchiveError("Arkivet indeholder kontroltegn i filnavn")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArchiveError("Arkivet indeholder path traversal eller absolut sti")
    if expected_root is not None and (not path.parts or path.parts[0] != expected_root):
        raise ArchiveError("Arkivmedlem ligger uden for det forventede root-katalog")
    return path


def inspect_payload_tar(path: Path, *, expected_root: str, limits: ArchiveLimits | None = None) -> list[tarfile.TarInfo]:
    selected = limits or ArchiveLimits()
    members: list[tarfile.TarInfo] = []
    seen: set[str] = set()
    total = 0
    with tarfile.open(path, mode="r:") as archive:
        for member in archive.getmembers():
            validate_member_name(member.name, expected_root=expected_root)
            if member.name in seen:
                raise ArchiveError("Arkivet indeholder dublerede medlemmer")
            seen.add(member.name)
            if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
                raise ArchiveError("Arkivet indeholder links eller specialfiler")
            if not (member.isfile() or member.isdir()):
                raise ArchiveError("Arkivet indeholder en ikke-understøttet medlemstype")
            if member.uid != 0 or member.gid != 0:
                raise ArchiveError("Arkivmedlemmer skal være root-ejede")
            if member.isfile():
                if member.size < 0 or member.size > selected.max_member_bytes:
                    raise ArchiveError("Arkivmedlem er for stort")
                total += member.size
                if total > selected.max_total_bytes:
                    raise ArchiveError("Arkivets samlede indhold er for stort")
            members.append(member)
            if len(members) > selected.max_files:
                raise ArchiveError("Arkivet indeholder for mange medlemmer")
    if not members:
        raise ArchiveError("Payloadarkivet er tomt")
    return members


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def read_bundle_artifacts_fd(descriptor: int) -> tuple[dict, bytes, bytes]:
    """Read manifest, payload and embedded fresh installer from one open bundle identity."""
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise ArchiveError("Releasebundlen skal være en almindelig fil")
    if metadata.st_size <= 0 or metadata.st_size > MAX_BUNDLE_BYTES:
        raise ArchiveError("Releasebundlens størrelse er ugyldig")
    seen: set[str] = set()
    manifest_bytes: bytes | None = None
    payload_bytes: bytes | None = None
    installer_bytes: bytes | None = None
    installer_name: str | None = None
    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(os.dup(descriptor), "rb", closefd=True) as source:
        with tarfile.open(fileobj=source, mode="r:") as archive:
            members = archive.getmembers()
            manifest_member = next((member for member in members if member.name == "manifest.json"), None)
            if manifest_member is None:
                raise ArchiveError("Releasebundlen mangler manifest")
            if not manifest_member.isfile() or manifest_member.uid != 0 or manifest_member.gid != 0 or manifest_member.mode & 0o022:
                raise ArchiveError("Releasebundle-manifestet har ugyldigt ejerskab eller mode")
            if manifest_member.size <= 0 or manifest_member.size > MAX_MANIFEST_BYTES:
                raise ArchiveError("Releasebundle-manifestet er for stort eller tomt")
            stream = archive.extractfile(manifest_member)
            if stream is None:
                raise ArchiveError("Releasebundle-manifestet kunne ikke læses")
            manifest_bytes = stream.read(manifest_member.size + 1)
            if len(manifest_bytes) != manifest_member.size:
                raise ArchiveError("Releasebundle-manifestet har forkert størrelse")
            try:
                manifest = json.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArchiveError("Releasebundlens manifest er ugyldigt") from exc
            if not isinstance(manifest, dict):
                raise ArchiveError("Releasebundlens manifest skal være et objekt")
            installer_name = str((manifest.get("fresh_installer") or {}).get("file") or "")
            if not installer_name:
                raise ArchiveError("Releasebundlens manifest mangler fresh_installer.file")
            validate_member_name(installer_name)

            allowed = {"manifest.json", "clientflow-payload.tar", installer_name}
            for member in members:
                validate_member_name(member.name)
                if member.name in seen:
                    raise ArchiveError("Releasebundlen indeholder dublerede medlemmer")
                seen.add(member.name)
                if not member.isfile() or member.name not in allowed:
                    raise ArchiveError("Releasebundlen indeholder uventede medlemmer")
                if member.uid != 0 or member.gid != 0 or member.mode & 0o022:
                    raise ArchiveError("Releasebundle-medlemmer har ugyldigt ejerskab eller mode")
                if member.name == "manifest.json":
                    continue
                limit = MAX_PAYLOAD_BYTES if member.name == "clientflow-payload.tar" else MAX_FRESH_INSTALLER_BYTES
                if member.size <= 0 or member.size > limit:
                    raise ArchiveError("Releasebundle-medlem er for stort eller tomt")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ArchiveError("Releasebundle-medlem kunne ikke læses")
                data = stream.read(member.size + 1)
                if len(data) != member.size:
                    raise ArchiveError("Releasebundle-medlem har forkert størrelse")
                if member.name == "clientflow-payload.tar":
                    payload_bytes = data
                elif member.name == installer_name:
                    installer_bytes = data
    after = os.fstat(descriptor)
    if _stat_signature(after) != _stat_signature(metadata):
        raise ArchiveError("Releasebundlen ændrede sig under læsning")
    os.lseek(descriptor, 0, os.SEEK_SET)
    expected = {"manifest.json", "clientflow-payload.tar", installer_name}
    if seen != expected or manifest_bytes is None or payload_bytes is None or installer_bytes is None:
        raise ArchiveError("Releasebundlen mangler manifest, payload eller fresh installer")
    return manifest, payload_bytes, installer_bytes


def read_bundle_fd(descriptor: int) -> tuple[dict, bytes]:
    """Compatibility wrapper for callers that only need manifest and payload."""
    manifest, payload, _installer = read_bundle_artifacts_fd(descriptor)
    return manifest, payload


def read_bundle(bundle: Path) -> tuple[dict, bytes]:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(bundle, flags)
    except FileNotFoundError as exc:
        raise ArchiveError("Releasebundlen findes ikke") from exc
    except OSError as exc:
        raise ArchiveError("Releasebundlen kunne ikke åbnes sikkert") from exc
    try:
        return read_bundle_fd(descriptor)
    finally:
        os.close(descriptor)
