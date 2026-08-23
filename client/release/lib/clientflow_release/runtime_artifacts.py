from __future__ import annotations

from pathlib import PurePosixPath
import stat
import tarfile
import zipfile

from clientflow_release_format.archive import FileRegion


class RuntimeArtifactError(ValueError):
    pass


MAX_PYTHON_RUNTIME_BYTES = 2 * 1024 * 1024 * 1024
MAX_PYTHON_MEMBER_BYTES = 1024 * 1024 * 1024

REQUIRED_DISTRIBUTIONS = {
    "clientflow-runtime": None,
    "pyjwt": "2.13.0",
    "websockets": "12.0",
    "evdev": "1.9.3",
    "pip": "26.1.2",
}


def _metadata_from_wheel(region: FileRegion) -> tuple[str, str]:
    try:
        with region.open() as source:
            with zipfile.ZipFile(source) as archive:
                if archive.testzip() is not None:
                    raise RuntimeArtifactError("Wheel ZIP-integritet fejlede")
                metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
                if len(metadata_names) != 1:
                    raise RuntimeArtifactError("Wheel mangler entydig METADATA")
                raw = archive.read(metadata_names[0]).decode("utf-8", errors="strict")
    except (zipfile.BadZipFile, UnicodeDecodeError, KeyError, OSError) as exc:
        raise RuntimeArtifactError("Wheel er ugyldig") from exc
    name = version = None
    for line in raw.splitlines():
        if line.startswith("Name: "):
            name = line[6:].strip().lower().replace("_", "-")
        elif line.startswith("Version: "):
            version = line[9:].strip()
    if not name or not version:
        raise RuntimeArtifactError("Wheel METADATA mangler Name/Version")
    return name, version


def _runtime_regions(payload: FileRegion, manifest: dict) -> dict[str, FileRegion]:
    root = str(manifest["payload"]["root"])
    expected_prefix = f"{root}/runtime-inputs/"
    actual: dict[str, FileRegion] = {}
    try:
        with payload.open() as source:
            with tarfile.open(fileobj=source, mode="r:") as archive:
                for member in archive.getmembers():
                    if not member.isfile() or not member.name.startswith(expected_prefix):
                        continue
                    relative = member.name[len(expected_prefix):]
                    if "/" in relative and not relative.startswith("wheelhouse/"):
                        continue
                    file_name = relative.removeprefix("wheelhouse/")
                    if not file_name or file_name in actual:
                        raise RuntimeArtifactError("Payloaden har dubleret runtimeartifact-identitet")
                    actual[file_name] = payload.subregion(member.offset_data, member.size)
    except (tarfile.TarError, OSError, ValueError) as exc:
        if isinstance(exc, RuntimeArtifactError):
            raise
        raise RuntimeArtifactError("Payloadens runtimeartifact-TAR er ugyldig") from exc
    return actual


def _validate_python_runtime(region: FileRegion) -> None:
    try:
        with region.open() as source:
            with tarfile.open(fileobj=source, mode="r:") as python_archive:
                members = python_archive.getmembers()
                names: set[str] = set()
                total_size = 0
                python_member = None
                for member in members:
                    name = PurePosixPath(member.name)
                    if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != "python-3.13.14":
                        raise RuntimeArtifactError("Python-runtime indeholder en ugyldig sti")
                    canonical = name.as_posix()
                    if canonical in names:
                        raise RuntimeArtifactError("Python-runtime indeholder dublerede medlemmer")
                    names.add(canonical)
                    if member.uid != 0 or member.gid != 0:
                        raise RuntimeArtifactError("Python-runtime er ikke root-owned")
                    if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
                        raise RuntimeArtifactError("Python-runtime indeholder links eller specialfiler")
                    if not (member.isdir() or member.isfile()):
                        raise RuntimeArtifactError("Python-runtime indeholder en ukendt filtype")
                    if member.size < 0 or member.size > MAX_PYTHON_MEMBER_BYTES:
                        raise RuntimeArtifactError("Python-runtime indeholder en for stor fil")
                    total_size += member.size
                    if total_size > MAX_PYTHON_RUNTIME_BYTES:
                        raise RuntimeArtifactError("Python-runtime overskrider størrelsesgrænsen")
                    if canonical == "python-3.13.14/bin/python3":
                        python_member = member
                if python_member is None or not python_member.isfile():
                    raise RuntimeArtifactError("Python-runtime mangler bin/python3")
                if not python_member.mode & stat.S_IXUSR:
                    raise RuntimeArtifactError("Python-runtime bin/python3 er ikke eksekverbar")
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeArtifactError("Python-runtime TAR er ugyldig") from exc


def validate_runtime_artifacts(payload: FileRegion, manifest: dict) -> None:
    """Deep-verify runtime artifacts without materializing payload-sized bytes."""
    version = str(manifest["version"])
    declared = {item["file"]: item for item in manifest["runtime"].get("artifacts") or []}
    actual = _runtime_regions(payload, manifest)
    if set(actual) != set(declared):
        raise RuntimeArtifactError("Payloadens runtimeartifacts matcher ikke manifestet")

    for name, region in actual.items():
        metadata = declared[name]
        if region.size != int(metadata["size"]) or region.sha256() != metadata["sha256"]:
            raise RuntimeArtifactError(f"Runtimeartifact hash/size matcher ikke: {name}")

    python_region = actual.get("python-runtime-amd64.tar")
    if python_region is None:
        raise RuntimeArtifactError("Python-runtime mangler")
    _validate_python_runtime(python_region)

    found: dict[str, str] = {}
    for name, region in actual.items():
        if not name.endswith(".whl"):
            continue
        distribution, artifact_version = _metadata_from_wheel(region)
        if distribution in found:
            raise RuntimeArtifactError(f"Dubleret wheel-distribution: {distribution}")
        found[distribution] = artifact_version
    expected = dict(REQUIRED_DISTRIBUTIONS)
    expected["clientflow-runtime"] = version
    if found != expected:
        raise RuntimeArtifactError(f"Wheelhouse har forkert distributionssæt: {found}")
