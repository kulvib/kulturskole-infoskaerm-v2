from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile

from .constants import (
    MAX_BUNDLE_BYTES,
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


def safe_extract_payload(path: Path, destination: Path, *, expected_root: str) -> Path:
    if destination.exists():
        raise ArchiveError("Ekstraktionsmålet findes allerede")
    destination.mkdir(mode=0o700, parents=True)
    inspect_payload_tar(path, expected_root=expected_root)
    with tarfile.open(path, mode="r:") as archive:
        archive.extractall(destination, filter="data")
    root = destination / expected_root
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ArchiveError("Payload-root blev ikke ekstraheret som katalog")
    return root


def read_bundle(bundle: Path) -> tuple[dict, bytes]:
    try:
        metadata = bundle.lstat()
    except FileNotFoundError as exc:
        raise ArchiveError("Releasebundlen findes ikke") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ArchiveError("Releasebundlen skal være en almindelig fil")
    if metadata.st_size <= 0 or metadata.st_size > MAX_BUNDLE_BYTES:
        raise ArchiveError("Releasebundlens størrelse er ugyldig")
    seen: set[str] = set()
    manifest_bytes: bytes | None = None
    payload_bytes: bytes | None = None
    with tarfile.open(bundle, mode="r:") as archive:
        for member in archive.getmembers():
            validate_member_name(member.name)
            if member.name in seen:
                raise ArchiveError("Releasebundlen indeholder dublerede medlemmer")
            seen.add(member.name)
            if not member.isfile() or member.name not in {"manifest.json", "clientflow-payload.tar"}:
                raise ArchiveError("Releasebundlen indeholder uventede medlemmer")
            if member.uid != 0 or member.gid != 0 or member.mode & 0o022:
                raise ArchiveError("Releasebundle-medlemmer har ugyldigt ejerskab eller mode")
            limit = MAX_MANIFEST_BYTES if member.name == "manifest.json" else MAX_PAYLOAD_BYTES
            if member.size <= 0 or member.size > limit:
                raise ArchiveError("Releasebundle-medlem er for stort eller tomt")
            stream = archive.extractfile(member)
            if stream is None:
                raise ArchiveError("Releasebundle-medlem kunne ikke læses")
            data = stream.read(member.size + 1)
            if len(data) != member.size:
                raise ArchiveError("Releasebundle-medlem har forkert størrelse")
            if member.name == "manifest.json":
                manifest_bytes = data
            else:
                payload_bytes = data
    if seen != {"manifest.json", "clientflow-payload.tar"} or manifest_bytes is None or payload_bytes is None:
        raise ArchiveError("Releasebundlen mangler manifest eller payload")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveError("Releasebundlens manifest er ugyldigt") from exc
    if not isinstance(manifest, dict):
        raise ArchiveError("Releasebundlens manifest skal være et objekt")
    return manifest, payload_bytes
