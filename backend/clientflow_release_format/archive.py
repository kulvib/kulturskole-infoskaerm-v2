from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
from typing import BinaryIO

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


class _BoundedReader(io.RawIOBase):
    """Seekable read-only view over one byte range in an already-open file.

    Reads use pread(2), so nested TAR/ZIP readers cannot disturb the position of
    the pinned outer bundle descriptor. Closing this view never closes the
    underlying descriptor; ownership stays with the bundle handle.
    """

    def __init__(self, descriptor: int, start: int, size: int):
        super().__init__()
        self._descriptor = descriptor
        self._start = start
        self._size = size
        self._position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        self._checkClosed()
        return self._position

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        self._checkClosed()
        if whence == os.SEEK_SET:
            position = offset
        elif whence == os.SEEK_CUR:
            position = self._position + offset
        elif whence == os.SEEK_END:
            position = self._size + offset
        else:
            raise ValueError("Ugyldig seek-whence")
        if position < 0:
            raise ValueError("Negativ seek-position")
        self._position = min(position, self._size)
        return self._position

    def read(self, size: int = -1) -> bytes:
        self._checkClosed()
        remaining = self._size - self._position
        if remaining <= 0:
            return b""
        if size is None or size < 0:
            size = remaining
        else:
            size = min(size, remaining)
        data = os.pread(self._descriptor, size, self._start + self._position)
        self._position += len(data)
        return data

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


@dataclass(frozen=True, slots=True)
class FileRegion:
    """Immutable description of a member range in one pinned bundle inode."""

    descriptor: int
    offset: int
    size: int
    _signature: tuple[int, int, int, int, int, int] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.offset < 0 or self.size < 0:
            raise ArchiveError("Arkivregion har ugyldig offset eller størrelse")
        metadata = os.fstat(self.descriptor)
        signature = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            metadata.st_nlink,
        )
        if self.offset + self.size > metadata.st_size:
            raise ArchiveError("Arkivregion ligger uden for den åbne fil")
        if self._signature is None:
            object.__setattr__(self, "_signature", signature)
        elif not self._same_data_identity(self._signature, signature):
            raise ArchiveError("Den pinnede bundle ændrede sig før regionen blev åbnet")

    @staticmethod
    def _same_data_identity(
        original: tuple[int, int, int, int, int, int],
        current: tuple[int, int, int, int, int, int],
    ) -> bool:
        if original == current:
            return True
        # Ren path-replacement/hardlink-topologi ændrer ctime+nlink på den
        # pinnede inode uden at ændre dens bytes. Det skal ikke bryde inode-
        # pinning-kontrakten. Size+mtime+dev+ino skal fortsat være identiske.
        return (
            original[0:4] == current[0:4]
            and original[5] != current[5]
        )

    def assert_unchanged(self) -> None:
        metadata = os.fstat(self.descriptor)
        signature = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            metadata.st_nlink,
        )
        if self._signature is None or not self._same_data_identity(self._signature, signature):
            raise ArchiveError("Den pinnede bundle ændrede sig under region-verifikation")

    def open(self) -> BinaryIO:
        self.assert_unchanged()
        return _BoundedReader(self.descriptor, self.offset, self.size)

    def subregion(self, offset: int, size: int) -> FileRegion:
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ArchiveError("Underregion ligger uden for den overordnede region")
        return FileRegion(self.descriptor, self.offset + offset, size, self._signature)

    def sha256(self, *, chunk_size: int = 1024 * 1024) -> str:
        if chunk_size <= 0:
            raise ValueError("chunk_size skal være positiv")
        self.assert_unchanged()
        digest = hashlib.sha256()
        position = 0
        while position < self.size:
            data = os.pread(
                self.descriptor,
                min(chunk_size, self.size - position),
                self.offset + position,
            )
            if not data:
                raise ArchiveError("Arkivregion sluttede før deklareret størrelse")
            digest.update(data)
            position += len(data)
        self.assert_unchanged()
        return digest.hexdigest()

    def read_small(self, *, max_bytes: int) -> bytes:
        if self.size > max_bytes:
            raise ArchiveError("Arkivmedlem er større end den tilladte memory-bound")
        with self.open() as source:
            data = source.read(self.size + 1)
        self.assert_unchanged()
        if len(data) != self.size:
            raise ArchiveError("Arkivmedlem har forkert størrelse")
        return data


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


def _inspect_payload_archive(
    archive: tarfile.TarFile,
    *,
    expected_root: str,
    limits: ArchiveLimits | None = None,
) -> list[tarfile.TarInfo]:
    selected = limits or ArchiveLimits()
    members: list[tarfile.TarInfo] = []
    seen: set[str] = set()
    total = 0
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


def inspect_payload_tar(path: Path, *, expected_root: str, limits: ArchiveLimits | None = None) -> list[tarfile.TarInfo]:
    with tarfile.open(path, mode="r:") as archive:
        return _inspect_payload_archive(archive, expected_root=expected_root, limits=limits)


def inspect_payload_region(
    region: FileRegion,
    *,
    expected_root: str,
    limits: ArchiveLimits | None = None,
) -> list[tarfile.TarInfo]:
    with region.open() as source:
        with tarfile.open(fileobj=source, mode="r:") as archive:
            members = _inspect_payload_archive(archive, expected_root=expected_root, limits=limits)
    region.assert_unchanged()
    return members


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def read_bundle_artifact_regions_fd(descriptor: int) -> tuple[dict, FileRegion, FileRegion]:
    """Parse outer bundle metadata without materializing payload or installer bytes."""
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise ArchiveError("Releasebundlen skal være en almindelig fil")
    if metadata.st_size <= 0 or metadata.st_size > MAX_BUNDLE_BYTES:
        raise ArchiveError("Releasebundlens størrelse er ugyldig")

    seen: set[str] = set()
    manifest: dict | None = None
    payload_region: FileRegion | None = None
    installer_region: FileRegion | None = None
    installer_name: str | None = None

    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(os.dup(descriptor), "rb", closefd=True) as source:
        with tarfile.open(fileobj=source, mode="r:") as archive:
            members = archive.getmembers()
            manifest_member = next((member for member in members if member.name == "manifest.json"), None)
            if manifest_member is None:
                raise ArchiveError("Releasebundlen mangler manifest")
            if (
                not manifest_member.isfile()
                or manifest_member.uid != 0
                or manifest_member.gid != 0
                or manifest_member.mode & 0o022
            ):
                raise ArchiveError("Releasebundle-manifestet har ugyldigt ejerskab eller mode")
            if manifest_member.size <= 0 or manifest_member.size > MAX_MANIFEST_BYTES:
                raise ArchiveError("Releasebundle-manifestet er for stort eller tomt")
            manifest_region = FileRegion(descriptor, manifest_member.offset_data, manifest_member.size)
            manifest_bytes = manifest_region.read_small(max_bytes=MAX_MANIFEST_BYTES)
            try:
                value = json.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArchiveError("Releasebundlens manifest er ugyldigt") from exc
            if not isinstance(value, dict):
                raise ArchiveError("Releasebundlens manifest skal være et objekt")
            manifest = value
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
                region = FileRegion(descriptor, member.offset_data, member.size)
                if member.name == "clientflow-payload.tar":
                    payload_region = region
                elif member.name == installer_name:
                    installer_region = region

    after = os.fstat(descriptor)
    if _stat_signature(after) != _stat_signature(metadata):
        raise ArchiveError("Releasebundlen ændrede sig under læsning")
    os.lseek(descriptor, 0, os.SEEK_SET)
    expected = {"manifest.json", "clientflow-payload.tar", installer_name}
    if seen != expected or manifest is None or payload_region is None or installer_region is None:
        raise ArchiveError("Releasebundlen mangler manifest, payload eller fresh installer")
    return manifest, payload_region, installer_region
