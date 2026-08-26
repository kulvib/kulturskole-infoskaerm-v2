from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Any, Callable

from .bundle import extract_verified_payload, open_verified_bundle
from .constants import INSTALL_MODE_UPDATE
from .crypto import sha256_file
from .filesystem import (
    atomic_symlink,
    atomic_write_bytes,
    atomic_write_json,
    ensure_real_directory,
    fsync_directory,
    load_secure_json,
    remove_tree_no_symlink,
)
from .runtime_prepare import prepare_runtime

_RELEASE_ID_RE = re.compile(r"^clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*$")
_APPROVAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,199}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
STATE_SCHEMA = 2


class TransactionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Layout:
    root: Path = Path("/")

    def path(self, absolute: str) -> Path:
        if not absolute.startswith("/"):
            raise ValueError("Layout paths must be absolute")
        if self.root == Path("/"):
            return Path(absolute)
        return self.root / absolute.lstrip("/")

    @property
    def install_root(self) -> Path:
        return self.path("/opt/clientflow")

    @property
    def releases(self) -> Path:
        return self.install_root / "releases"

    @property
    def active(self) -> Path:
        return self.install_root / "active"

    @property
    def state_root(self) -> Path:
        return self.path("/var/lib/clientflow/release")

    @property
    def state_file(self) -> Path:
        return self.state_root / "state.json"

    @property
    def lock_file(self) -> Path:
        return self.state_root / "transaction.lock"

    @property
    def unit_root(self) -> Path:
        return self.path("/etc/systemd/system")

    @property
    def sysusers_file(self) -> Path:
        return self.path("/usr/lib/sysusers.d/clientflow.conf")

    @property
    def tmpfiles_file(self) -> Path:
        return self.path("/usr/lib/tmpfiles.d/clientflow.conf")

    @property
    def stable_support_root(self) -> Path:
        return self.path("/usr/lib/clientflow")

    @property
    def stable_updater_root(self) -> Path:
        return self.stable_support_root / "updater"

    @property
    def stable_updater_pyz(self) -> Path:
        return self.stable_updater_root / "clientflow-updater.pyz"


class TransactionLock:
    def __init__(self, layout: Layout) -> None:
        self.layout = layout
        self.fd: int | None = None

    def __enter__(self):
        ensure_real_directory(self.layout.state_root, mode=0o700)
        self.fd = os.open(self.layout.lock_file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_args):
        assert self.fd is not None
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _initial_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA,
        "highest_release_sequence": 0,
        "active_release_id": None,
        "previous_release_id": None,
        "staged_release_id": None,
        "activation_intent": None,
        "installed": {},
        "history": [],
    }


def load_state(layout: Layout) -> dict[str, Any]:
    if not layout.state_file.exists():
        return _initial_state()
    state = load_secure_json(layout.state_file)
    if state.get("schema_version") != STATE_SCHEMA:
        raise TransactionError("Release state har forkert schema")
    if not isinstance(state.get("installed"), dict) or not isinstance(state.get("history"), list):
        raise TransactionError("Release state er korrupt")
    return state


def save_state(layout: Layout, state: dict[str, Any]) -> None:
    state["schema_version"] = STATE_SCHEMA
    state["history"] = list(state.get("history") or [])[-200:]
    atomic_write_json(layout.state_file, state, mode=0o600)


def _append_history(state: dict[str, Any], event: str, **details: Any) -> None:
    state.setdefault("history", []).append({"at": _now(), "event": event, **details})


def _validate_release_id(value: str) -> str:
    if not _RELEASE_ID_RE.fullmatch(value):
        raise TransactionError("release_id er ugyldigt")
    return value


def _validate_approval(value: str) -> str:
    if not _APPROVAL_RE.fullmatch(value):
        raise TransactionError("approval_reference er ugyldig")
    return value


def _read_active_release_id(layout: Layout) -> str | None:
    try:
        metadata = layout.active.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISLNK(metadata.st_mode):
        raise TransactionError("/opt/clientflow/active er ikke et symlink")
    target = os.readlink(layout.active)
    target_path = (layout.active.parent / target).resolve(strict=False)
    releases_root = layout.releases.resolve(strict=False)
    if target_path.parent != releases_root:
        raise TransactionError("Active-symlink peger uden for releases-kataloget")
    release_id = target_path.name
    _validate_release_id(release_id)
    return release_id


def _manifest_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _manifest_provenance(
    manifest: dict[str, Any],
    *,
    bundle_size: int,
    bundle_sha256: str,
) -> dict[str, Any]:
    approval = manifest.get("release_approval") or {}
    source = manifest.get("source") or {}
    reference = _validate_approval(str(approval.get("reference") or ""))
    candidate_sha256 = str(approval.get("candidate_sha256") or "").strip().lower()
    source_commit = str(source.get("commit") or "").strip().lower()
    bundle_sha256 = str(bundle_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(candidate_sha256):
        raise TransactionError("Release manifest mangler canonical candidate SHA-256")
    if not _COMMIT_RE.fullmatch(source_commit):
        raise TransactionError("Release manifest mangler canonical source commit")
    if not _SHA256_RE.fullmatch(bundle_sha256):
        raise TransactionError("Staged bundle mangler canonical SHA-256")
    if not isinstance(bundle_size, int) or bundle_size <= 0:
        raise TransactionError("Staged bundle mangler canonical størrelse")
    return {
        "bundle_sha256": bundle_sha256,
        "bundle_size": bundle_size,
        "release_approval_reference": reference,
        "release_candidate_sha256": candidate_sha256,
        "source_commit": source_commit,
    }


def _assert_record_provenance(record: dict[str, Any], provenance: dict[str, Any]) -> None:
    for key, expected in provenance.items():
        if record.get(key) != expected:
            raise TransactionError(f"Installeret release har inkonsistent provenance: {key}")


def _canonical_activation_approval(
    layout: Layout,
    state: dict[str, Any],
    release_id: str,
    *,
    expected_approval_reference: str,
) -> str:
    installed = state.get("installed") or {}
    record = installed.get(release_id)
    if not isinstance(record, dict):
        raise TransactionError("Releasen er ikke staged")
    release_root = layout.releases / release_id
    manifest = load_secure_json(
        release_root / "release-manifest.json",
        max_bytes=8 * 1024 * 1024,
        forbidden_mode_bits=0o022,
    )
    if manifest.get("release_id") != release_id:
        raise TransactionError("Staged release-manifest matcher ikke release_id")
    if record.get("manifest_sha256") != _manifest_digest(manifest):
        raise TransactionError("Staged release-manifest matcher ikke release-state")
    provenance = _manifest_provenance(
        manifest,
        bundle_size=int(record.get("bundle_size") or 0),
        bundle_sha256=str(record.get("bundle_sha256") or ""),
    )
    _assert_record_provenance(record, provenance)
    expected = _validate_approval(expected_approval_reference)
    canonical = provenance["release_approval_reference"]
    if expected != canonical:
        raise TransactionError(
            "approval_reference matcher ikke den immutable release-approval, som er bundet til artifactet"
        )
    return canonical


def _fsync_tree(root: Path) -> None:
    directories: list[Path] = [root]
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise TransactionError(f"Symlink blev fundet i releasekataloget: {path}")
        if stat.S_ISDIR(metadata.st_mode):
            directories.append(path)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise TransactionError(f"Specialfil blev fundet i releasekataloget: {path}")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory)


def _source_tree_digest(root: Path) -> str:
    """Digest only files originating in the verified payload, excluding generated runtime state."""
    excluded_roots = {"runtime", "runtime-python", ".python-extract"}
    excluded_files = {"release-ready.json", "release-manifest.json"}
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in excluded_roots:
            continue
        if relative.as_posix() in excluded_files:
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise TransactionError(f"Symlink blev fundet i releasekataloget: {path}")
        encoded = relative.as_posix().encode("utf-8")
        if stat.S_ISDIR(metadata.st_mode):
            digest.update(b"D\0" + encoded + b"\0")
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise TransactionError(f"Specialfil blev fundet i releasekataloget: {path}")
        file_digest = hashlib.sha256()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            while chunk := os.read(descriptor, 1024 * 1024):
                file_digest.update(chunk)
        finally:
            os.close(descriptor)
        executable = b"1" if metadata.st_mode & stat.S_IXUSR else b"0"
        digest.update(
            b"F\0"
            + encoded
            + b"\0"
            + executable
            + b"\0"
            + str(metadata.st_size).encode("ascii")
            + b"\0"
            + file_digest.digest()
        )
    return digest.hexdigest()


def _make_immutable(root: Path, *, seal_root: bool = True) -> None:
    _fsync_tree(root)
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise TransactionError(f"Symlink blev fundet i releasekataloget: {path}")
        if stat.S_ISDIR(metadata.st_mode):
            os.chmod(path, 0o555)
        elif stat.S_ISREG(metadata.st_mode):
            executable = bool(metadata.st_mode & stat.S_IXUSR)
            os.chmod(path, 0o555 if executable else 0o444)
        else:
            raise TransactionError(f"Specialfil blev fundet i releasekataloget: {path}")
    os.chmod(root, 0o555 if seal_root else 0o755)
    _fsync_tree(root)
    fsync_directory(root.parent)


def _seal_published_release(root: Path) -> None:
    """Seal an atomically published release root before state is committed."""
    try:
        metadata = root.lstat()
    except FileNotFoundError as exc:
        raise TransactionError(
            "Publiceret releasekatalog mangler under forsegling"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise TransactionError(
            "Publiceret releasekatalog er ugyldigt under forsegling"
        )
    os.chmod(root, 0o555)
    _fsync_tree(root)
    fsync_directory(root.parent)


def _validate_release_tree(release_root: Path, manifest: dict[str, Any]) -> None:
    if (release_root / "VERSION").read_text(encoding="utf-8").strip() != manifest["version"]:
        raise TransactionError("Payloadens VERSION matcher ikke manifestet")
    required = (
        "client-runtime/systemd/clientflow.target",
        "client-runtime/sysusers.d/clientflow.conf",
        "client-runtime/tmpfiles.d/clientflow.conf",
        "release/bin/clientflow-release-transaction",
        "release/updater/clientflow-updater.pyz",
        "release/lib/clientflow_release/transaction.py",
        "release/lib/clientflow_release_format/manifest.py",
    )
    for relative in required:
        path = release_root / relative
        if not path.is_file() or path.is_symlink():
            raise TransactionError(f"Releasepayloaden mangler {relative}")


def _validate_prepared_release_tree(release_root: Path, manifest: dict[str, Any]) -> None:
    _validate_release_tree(release_root, manifest)
    ready_path = release_root / "release-ready.json"
    runtime_python = release_root / "runtime/bin/python"
    helper_path = release_root / "release/bin/clientflow-release-transaction"
    for path in (ready_path, runtime_python, helper_path):
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise TransactionError(f"Forberedt release mangler {path.relative_to(release_root)}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise TransactionError(f"Forberedt releasefil er ugyldig: {path.relative_to(release_root)}")
    if not os.access(runtime_python, os.X_OK):
        raise TransactionError("Forberedt runtime-Python er ikke eksekverbar")
    ready = load_secure_json(ready_path, max_bytes=64 * 1024, forbidden_mode_bits=0o022)
    expected = {
        "version": manifest["version"],
        "release_id": manifest["release_id"],
        "release_sequence": int(manifest["release_sequence"]),
        "python": "3.13.14",
    }
    for key, value in expected.items():
        if ready.get(key) != value:
            raise TransactionError(f"release-ready.json matcher ikke manifestet: {key}")
    try:
        with helper_path.open("r", encoding="utf-8") as helper_file:
            first_line = helper_file.readline().rstrip("\n")
    except UnicodeDecodeError as exc:
        raise TransactionError("Releasehelperens shebang kunne ikke læses") from exc
    if first_line != "#!/opt/clientflow/active/runtime/bin/python":
        raise TransactionError("Releasehelperen bruger ikke den aktive, bundlede runtime")


def stage_bundle(
    bundle: Path,
    *,
    release_id: str,
    expected_bundle_sha256: str,
    install_mode: str = INSTALL_MODE_UPDATE,
    layout: Layout = Layout(),
) -> dict[str, Any]:
    release_id = _validate_release_id(release_id)
    expected_bundle_sha256 = str(expected_bundle_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected_bundle_sha256):
        raise TransactionError("expected_bundle_sha256 er ugyldig")

    bundle_handle = None
    try:
        try:
            manifest, payload, bundle_size, actual_bundle_sha256, bundle_handle = open_verified_bundle(
                bundle,
                require_deployable=True,
                required_install_mode=install_mode,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            raise TransactionError(f"Releasebundlen kunne ikke verificeres sikkert: {exc}") from exc
        if actual_bundle_sha256 != expected_bundle_sha256:
            raise TransactionError("Releasebundlens SHA-256 matcher ikke den godkendte bundle-hash")
        if manifest["release_id"] != release_id:
            raise TransactionError("Bundle og release_id matcher ikke")

        provenance = _manifest_provenance(
            manifest,
            bundle_size=bundle_size,
            bundle_sha256=actual_bundle_sha256,
        )

        # Keep the verified bundle inode pinned for the complete extraction.
        # The payload is a bounded view into this exact handle, so no pathname
        # reopen or payload-sized memory copy participates in staging.
        with TransactionLock(layout):
            state = load_state(layout)
            sequence = int(manifest["release_sequence"])
            highest = int(state.get("highest_release_sequence") or 0)
            installed = state.setdefault("installed", {})
            final_root = layout.releases / release_id
            digest = _manifest_digest(manifest)
            if release_id in installed:
                record = installed[release_id]
                try:
                    final_metadata = final_root.lstat()
                except FileNotFoundError as exc:
                    raise TransactionError("Installeret release mangler på disk") from exc
                if stat.S_ISLNK(final_metadata.st_mode) or not stat.S_ISDIR(final_metadata.st_mode):
                    raise TransactionError("Installeret releasekatalog er ugyldigt")
                existing_manifest = load_secure_json(
                    final_root / "release-manifest.json",
                    max_bytes=8 * 1024 * 1024,
                    forbidden_mode_bits=0o022,
                )
                if record.get("manifest_sha256") != digest or _manifest_digest(existing_manifest) != digest:
                    raise TransactionError("Installeret release har samme ID men andet indhold")
                _assert_record_provenance(record, provenance)
                _validate_prepared_release_tree(final_root, existing_manifest)
                state["staged_release_id"] = release_id
                _append_history(
                    state,
                    "stage_idempotent",
                    release_id=release_id,
                    bundle_sha256=actual_bundle_sha256,
                    release_approval_reference=provenance["release_approval_reference"],
                )
                save_state(layout, state)
                return {"status": "already_staged", "release_id": release_id, "release_sequence": sequence}
            if sequence <= highest:
                raise TransactionError("Anti-rollback afviste en ikke-stigende release sequence")
            ensure_real_directory(layout.releases, mode=0o755)
            if final_root.exists() or final_root.is_symlink():
                try:
                    final_metadata = final_root.lstat()
                except FileNotFoundError as exc:  # pragma: no cover - race protection
                    raise TransactionError("Releasekataloget forsvandt under recovery") from exc
                if stat.S_ISLNK(final_metadata.st_mode) or not stat.S_ISDIR(final_metadata.st_mode):
                    raise TransactionError("Orphan releasekatalog er ugyldigt")
                existing_manifest = load_secure_json(
                    final_root / "release-manifest.json",
                    max_bytes=8 * 1024 * 1024,
                    forbidden_mode_bits=0o022,
                )
                if _manifest_digest(existing_manifest) != digest:
                    raise TransactionError("Orphan releasekatalog matcher ikke den verificerede bundle")
                _validate_prepared_release_tree(final_root, existing_manifest)
                recovery_parent = Path(tempfile.mkdtemp(prefix=f".{release_id}.recovery.", dir=layout.releases))
                try:
                    source_root = extract_verified_payload(
                        payload,
                        recovery_parent / "payload",
                        expected_root=manifest["payload"]["root"],
                    )
                    payload.assert_unchanged()
                    if _source_tree_digest(source_root) != _source_tree_digest(final_root):
                        raise TransactionError("Orphan releasekatalogets source tree matcher ikke den verificerede bundle")
                finally:
                    shutil.rmtree(recovery_parent, ignore_errors=True)
                _seal_published_release(final_root)
                installed[release_id] = {
                    "version": manifest["version"],
                    "release_sequence": sequence,
                    "manifest_sha256": digest,
                    **provenance,
                    "staged_at": _now(),
                    "recovered_after_interrupted_stage": True,
                }
                state["highest_release_sequence"] = sequence
                state["staged_release_id"] = release_id
                _append_history(
                    state,
                    "stage_recovered",
                    release_id=release_id,
                    release_sequence=sequence,
                    bundle_sha256=actual_bundle_sha256,
                    release_approval_reference=provenance["release_approval_reference"],
                )
                save_state(layout, state)
                return {"status": "recovered_staged", "release_id": release_id, "release_sequence": sequence}
            temp_parent = Path(tempfile.mkdtemp(prefix=f".{release_id}.", dir=layout.releases))
            try:
                extracted_root = extract_verified_payload(
                    payload,
                    temp_parent / "payload",
                    expected_root=manifest["payload"]["root"],
                )
                payload.assert_unchanged()
                staged_root = temp_parent / release_id
                os.replace(extracted_root, staged_root)
                remove_tree_no_symlink(temp_parent / "payload")
                _validate_release_tree(staged_root, manifest)
                prepare_runtime(staged_root, manifest)
                atomic_write_json(staged_root / "release-manifest.json", manifest, mode=0o444)
                _validate_prepared_release_tree(staged_root, manifest)
                _make_immutable(staged_root, seal_root=False)
                os.replace(staged_root, final_root)
                _seal_published_release(final_root)
                temp_parent.rmdir()
            except Exception:
                if temp_parent.exists():
                    shutil.rmtree(temp_parent, ignore_errors=True)
                raise
            installed[release_id] = {
                "version": manifest["version"],
                "release_sequence": sequence,
                "manifest_sha256": digest,
                **provenance,
                "staged_at": _now(),
            }
            state["highest_release_sequence"] = sequence
            state["staged_release_id"] = release_id
            _append_history(
                state,
                "staged",
                release_id=release_id,
                release_sequence=sequence,
                bundle_sha256=actual_bundle_sha256,
                release_approval_reference=provenance["release_approval_reference"],
            )
            save_state(layout, state)
            return {"status": "staged", "release_id": release_id, "release_sequence": sequence}
    finally:
        if bundle_handle is not None:
            bundle_handle.close()


def _atomic_copy(source: Path, destination: Path, *, mode: int) -> None:
    if not source.is_file() or source.is_symlink():
        raise TransactionError(f"Managed source er ugyldig: {source}")
    atomic_write_bytes(destination, source.read_bytes(), mode=mode)


def _managed_unit_paths(layout: Layout) -> list[Path]:
    if not layout.unit_root.exists():
        return []
    paths: set[Path] = set()
    for pattern in ("clientflow*.service", "clientflow*.socket", "clientflow*.target", "clientflow*.timer"):
        paths.update(layout.unit_root.glob(pattern))
    target = layout.unit_root / "clientflow.target"
    if target.exists() or target.is_symlink():
        paths.add(target)
    return sorted(paths)


def _remove_managed_units(layout: Layout) -> None:
    for path in _managed_unit_paths(layout):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise TransactionError(f"Managed systemd-definition er ikke en almindelig fil: {path}")
        path.unlink()
    if layout.unit_root.exists():
        fsync_directory(layout.unit_root)


def _validated_kiosk_user(value: str) -> str:
    value = str(value or "").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value):
        raise TransactionError("kiosk-user i managed definition er ugyldig")
    if value == "root" or value.startswith("clientflow"):
        raise TransactionError("kiosk-user i managed definition er ugyldig")
    return value


def _definition_kiosk_user(layout: Layout, explicit: str | None) -> str:
    if explicit:
        return _validated_kiosk_user(explicit)
    identity_path = layout.path("/etc/clientflow/identity.json")
    try:
        identity = load_secure_json(identity_path, max_bytes=64 * 1024, forbidden_mode_bits=0o077)
        return _validated_kiosk_user(str(identity["kiosk_user"]))
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise TransactionError("Kiosk-user kunne ikke læses fra ClientFlow identity") from exc


def _apply_definitions(
    layout: Layout,
    release_root: Path,
    *,
    kiosk_user: str | None = None,
) -> list[str]:
    unit_source = release_root / "client-runtime/systemd"
    ensure_real_directory(layout.unit_root, mode=0o755)
    _remove_managed_units(layout)
    unit_names: list[str] = []
    for source in sorted(unit_source.iterdir()):
        if source.suffix not in {".service", ".socket", ".target", ".timer"}:
            continue
        if not source.name.startswith("clientflow"):
            raise TransactionError("Uventet systemd unit i releasepayload")
        raw = source.read_bytes()
        placeholder = b"@CLIENTFLOW_KIOSK_USER@"
        if placeholder in raw:
            resolved = _definition_kiosk_user(layout, kiosk_user).encode("ascii")
            raw = raw.replace(placeholder, resolved)
        atomic_write_bytes(layout.unit_root / source.name, raw, mode=0o644)
        unit_names.append(source.name)
    _atomic_copy(release_root / "client-runtime/sysusers.d/clientflow.conf", layout.sysusers_file, mode=0o644)
    _atomic_copy(release_root / "client-runtime/tmpfiles.d/clientflow.conf", layout.tmpfiles_file, mode=0o644)
    return unit_names


def _remove_definitions(layout: Layout) -> None:
    _remove_managed_units(layout)
    for path in (layout.sysusers_file, layout.tmpfiles_file):
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise TransactionError(f"Managed definition er ikke en almindelig fil: {path}")
            path.unlink()
            fsync_directory(path.parent)


def _run(command: list[str], *, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if check and result.returncode != 0:
        raise TransactionError(f"Kommando fejlede ({result.returncode}): {' '.join(command)}\n{result.stdout[-4000:]}")
    return result


def _systemd_prepare(layout: Layout) -> None:
    if layout.root != Path("/"):
        return
    _run(["/usr/bin/systemd-sysusers", str(layout.sysusers_file)])
    _run(["/usr/bin/systemd-tmpfiles", "--create", str(layout.tmpfiles_file)])
    _run(["/usr/bin/systemctl", "daemon-reload"])


_UPDATE_CONTROL_PLANE_UNITS = frozenset({
    "clientflow-updater.service",
    "clientflow-updater.timer",
    "clientflow-update-controller.service",
})


def _runtime_unit_names(layout: Layout) -> list[str]:
    names = {path.name for path in _managed_unit_paths(layout)}
    return sorted(name for name in names if name not in _UPDATE_CONTROL_PLANE_UNITS)


def _quiesce_runtime(layout: Layout, *, require_target: bool = True) -> None:
    if layout.root != Path("/"):
        return
    units = _runtime_unit_names(layout)
    if require_target and "clientflow.target" not in units:
        raise TransactionError("Canonical clientflow.target mangler før runtime-quiesce")
    if not units:
        return
    _run(["/usr/bin/systemctl", "stop", *units])
    still_active: list[str] = []
    for unit in units:
        result = _run(
            ["/usr/bin/systemctl", "show", unit, "-p", "ActiveState", "--value"],
            check=False,
        )
        state = result.stdout.strip() if result.returncode == 0 else ""
        if state not in {"inactive", "failed"}:
            still_active.append(f"{unit}={state or 'unknown'}")
    if still_active:
        raise TransactionError(
            "ClientFlow runtime kunne ikke quiesces før release-swap: " + ", ".join(still_active)
        )


def _start_target(layout: Layout) -> None:
    if layout.root == Path("/"):
        _run(["/usr/bin/systemctl", "enable", "clientflow.target"])
        _run(["/usr/bin/systemctl", "start", "clientflow.target"])


def _disable_target(layout: Layout) -> None:
    if layout.root == Path("/"):
        _run(["/usr/bin/systemctl", "disable", "clientflow.target"])


def _expected_active_units(release_root: Path) -> tuple[list[str], list[str]]:
    services: list[str] = []
    sockets: list[str] = []
    for path in (release_root / "client-runtime/systemd").iterdir():
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".socket":
            sockets.append(path.name)
        elif path.suffix == ".service" and "WantedBy=clientflow.target" in text:
            services.append(path.name)
    return sorted(services), sorted(sockets)


def _health_check(layout: Layout, release_id: str, *, timeout: int) -> None:
    active = _read_active_release_id(layout)
    if active != release_id:
        raise TransactionError("Active-symlink matcher ikke den forventede release")
    release_root = layout.releases / release_id
    manifest = load_secure_json(
        release_root / "release-manifest.json",
        max_bytes=8 * 1024 * 1024,
        forbidden_mode_bits=0o022,
    )
    _validate_prepared_release_tree(release_root, manifest)
    if layout.root != Path("/"):
        return
    services, sockets = _expected_active_units(release_root)
    deadline = time.monotonic() + timeout
    pending = services + sockets
    while time.monotonic() < deadline:
        failed = []
        for unit in pending:
            result = _run(["/usr/bin/systemctl", "is-active", "--quiet", unit], check=False)
            if result.returncode != 0:
                failed.append(unit)
        if not failed:
            return
        time.sleep(2)
    raise TransactionError(f"Health checks fejlede for: {', '.join(failed)}")


def _switch_active(layout: Layout, release_id: str) -> None:
    _validate_release_id(release_id)
    release_root = layout.releases / release_id
    try:
        metadata = release_root.lstat()
    except FileNotFoundError as exc:
        raise TransactionError("Målreleasen er ikke installeret") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise TransactionError("Målreleasen er ikke et reelt katalog")
    atomic_symlink(f"releases/{release_id}", layout.active)


def _activation_intent(
    layout: Layout,
    state: dict[str, Any],
    *,
    release_id: str,
    release_approval_reference: str,
    current_release_id: str | None,
) -> tuple[dict[str, Any], bool]:
    existing = state.get("activation_intent")
    if existing is not None:
        if not isinstance(existing, dict):
            raise TransactionError("Release state har ugyldig activation_intent")
        if (
            existing.get("release_id") != release_id
            or existing.get("release_approval_reference") != release_approval_reference
        ):
            raise TransactionError("En anden activation er allerede committed lokalt")
        previous = existing.get("previous_release_id")
        if previous is not None:
            previous = _validate_release_id(str(previous))
        expected_previous = state.get("active_release_id")
        if expected_previous != previous:
            raise TransactionError("Activation-intent matcher ikke den durable pre-activation state")
        if current_release_id not in {previous, release_id}:
            raise TransactionError("Active-symlink matcher hverken activation target eller oprindelig release")
        return existing, False

    if current_release_id == release_id:
        if state.get("active_release_id") == release_id:
            return {
                "release_id": release_id,
                "previous_release_id": state.get("previous_release_id"),
                "release_approval_reference": release_approval_reference,
                "started_at": None,
            }, False
        raise TransactionError("Target er aktivt uden durable activation-intent")

    if state.get("active_release_id") != current_release_id:
        raise TransactionError("Durable active release-state matcher ikke active-symlink før activation")
    intent = {
        "release_id": release_id,
        "previous_release_id": current_release_id,
        "release_approval_reference": release_approval_reference,
        "started_at": _now(),
    }
    state["activation_intent"] = intent
    _append_history(
        state,
        "activation_intent_committed",
        release_id=release_id,
        previous_release_id=current_release_id,
        release_approval_reference=release_approval_reference,
    )
    save_state(layout, state)
    return intent, True


def _activate_release(
    layout: Layout,
    state: dict[str, Any],
    release_id: str,
    release_approval_reference: str,
) -> dict[str, Any]:
    installed = state.get("installed") or {}
    if release_id not in installed:
        raise TransactionError("Releasen er ikke staged")
    current = _read_active_release_id(layout)
    if current == release_id and state.get("active_release_id") == release_id and state.get("activation_intent") is None:
        return {"status": "already_active", "release_id": release_id}

    intent, _created = _activation_intent(
        layout,
        state,
        release_id=release_id,
        release_approval_reference=release_approval_reference,
        current_release_id=current,
    )
    previous = intent.get("previous_release_id")
    release_root = layout.releases / release_id
    _quiesce_runtime(layout)
    try:
        # Re-applying the exact target definitions is deliberate: after a crash we
        # cannot know whether the previous process died before or after the unit
        # swap. The immutable staged release makes this operation idempotent.
        _apply_definitions(layout, release_root)
        _switch_active(layout, release_id)
        _systemd_prepare(layout)
        _start_target(layout)
        manifest = json.loads((release_root / "release-manifest.json").read_text())
        _health_check(layout, release_id, timeout=int(manifest["activation"]["health_timeout_seconds"]))
    except Exception as activation_error:
        _quiesce_runtime(layout)
        try:
            if previous:
                previous_root = layout.releases / previous
                _apply_definitions(layout, previous_root)
                _switch_active(layout, previous)
                _systemd_prepare(layout)
                _start_target(layout)
                _health_check(layout, previous, timeout=120)
            else:
                _disable_target(layout)
                layout.active.unlink(missing_ok=True)
                _remove_definitions(layout)
                if layout.root == Path("/"):
                    _run(["/usr/bin/systemctl", "daemon-reload"])
        except Exception as rollback_error:
            _append_history(
                state,
                "automatic_rollback_failed",
                release_id=release_id,
                previous_release_id=previous,
                error=type(rollback_error).__name__,
            )
            save_state(layout, state)
            raise TransactionError("Aktivering og automatisk rollback fejlede") from rollback_error
        state["active_release_id"] = previous
        state["previous_release_id"] = None
        state["activation_intent"] = None
        _append_history(
            state,
            "automatic_rollback_completed",
            failed_release_id=release_id,
            restored_release_id=previous,
            error=type(activation_error).__name__,
        )
        save_state(layout, state)
        raise TransactionError("Aktivering fejlede; tidligere release blev automatisk gendannet") from activation_error
    state["previous_release_id"] = previous
    state["active_release_id"] = release_id
    state["staged_release_id"] = None
    state["activation_intent"] = None
    installed[release_id]["activated_at"] = _now()
    _append_history(
        state,
        "activated",
        release_id=release_id,
        previous_release_id=previous,
        release_approval_reference=release_approval_reference,
    )
    save_state(layout, state)
    return {"status": "active", "release_id": release_id, "previous_release_id": previous}


def activate_release(
    release_id: str,
    *,
    expected_release_approval_reference: str,
    layout: Layout = Layout(),
    first_activation_authorizer: Callable[[Layout], None] | None = None,
) -> dict[str, Any]:
    release_id = _validate_release_id(release_id)
    with TransactionLock(layout):
        state = load_state(layout)
        canonical_reference = _canonical_activation_approval(
            layout,
            state,
            release_id,
            expected_approval_reference=expected_release_approval_reference,
        )
        if _read_active_release_id(layout) is None:
            if first_activation_authorizer is None:
                raise TransactionError(
                    "Fresh first activation kræver et backend-approved client proof før lokal mutation"
                )
            try:
                first_activation_authorizer(layout)
            except Exception as exc:
                raise TransactionError(
                    "Fresh first activation kræver et backend-approved client proof før lokal mutation"
                ) from exc
        return _activate_release(layout, state, release_id, canonical_reference)


def rollback_release(
    *,
    expected_release_approval_reference: str,
    reason: str,
    release_id: str | None = None,
    layout: Layout = Layout(),
) -> dict[str, Any]:
    reason = reason.strip()
    if not 3 <= len(reason) <= 500 or any(ord(char) < 32 and char not in "\t" for char in reason):
        raise TransactionError("Rollback-begrundelsen er ugyldig")
    with TransactionLock(layout):
        state = load_state(layout)
        current = _read_active_release_id(layout)
        target = _validate_release_id(release_id) if release_id else state.get("previous_release_id")
        if not target or target == current:
            raise TransactionError("Der findes ingen anden installeret release at rulle tilbage til")
        if target not in (state.get("installed") or {}):
            raise TransactionError("Rollbackmålet er ikke installeret")
        approval = _canonical_activation_approval(
            layout,
            state,
            target,
            expected_approval_reference=expected_release_approval_reference,
        )
        result = _activate_release(layout, state, target, approval)
        state = load_state(layout)
        _append_history(
            state,
            "manual_rollback",
            from_release_id=current,
            to_release_id=target,
            reason=reason,
            release_approval_reference=approval,
        )
        save_state(layout, state)
        result["rollback_reason"] = reason
        return result


def status(layout: Layout = Layout()) -> dict[str, Any]:
    with TransactionLock(layout):
        state = load_state(layout)
        state = dict(state)
        state["active_symlink_release_id"] = _read_active_release_id(layout)
        return state


def install_stable_updater_host(
    release_id: str,
    *,
    layout: Layout = Layout(),
) -> dict[str, Any]:
    """Materialize and enable the unprivileged updater bootstrap plane only."""
    release_id = _validate_release_id(release_id)
    with TransactionLock(layout):
        state = load_state(layout)
        if release_id not in (state.get("installed") or {}):
            raise TransactionError("Stable updater kræver en staged release")
        release_root = layout.releases / release_id
        source = release_root / "release/updater/clientflow-updater.pyz"
        try:
            source_meta = source.lstat()
        except FileNotFoundError as exc:
            raise TransactionError("Staged release mangler stable updater-PYZ") from exc
        if stat.S_ISLNK(source_meta.st_mode) or not stat.S_ISREG(source_meta.st_mode):
            raise TransactionError("Stable updater-PYZ i staged release er ugyldig")
        if not source_meta.st_mode & stat.S_IXUSR:
            raise TransactionError("Stable updater-PYZ i staged release er ikke eksekverbar")

        ensure_real_directory(layout.stable_support_root, mode=0o755)
        ensure_real_directory(layout.stable_updater_root, mode=0o755)
        source_size, source_sha256 = sha256_file(source)
        _atomic_copy(source, layout.stable_updater_pyz, mode=0o555)
        installed_size, installed_sha256 = sha256_file(layout.stable_updater_pyz)
        if (installed_size, installed_sha256) != (source_size, source_sha256):
            raise TransactionError("Stable updater-PYZ matcher ikke den verificerede releasepayload")

        if layout.root == Path("/"):
            installed_meta = layout.stable_updater_pyz.lstat()
            if installed_meta.st_uid != 0 or installed_meta.st_gid != 0:
                raise TransactionError("Stable updater-PYZ skal være root-owned")
            _run(["/usr/bin/systemctl", "daemon-reload"])
            _run(["/usr/bin/systemctl", "enable", "--now", "clientflow-updater.timer"])

        _append_history(
            state,
            "stable_updater_host_installed",
            release_id=release_id,
            updater_sha256=installed_sha256,
        )
        save_state(layout, state)
        return {
            "status": "stable_updater_host_installed",
            "release_id": release_id,
            "updater_sha256": installed_sha256,
            "updater_path": str(layout.stable_updater_pyz),
        }


def install_staged_definitions(
    release_id: str,
    *,
    layout: Layout = Layout(),
    kiosk_user: str | None = None,
) -> dict[str, Any]:
    release_id = _validate_release_id(release_id)
    with TransactionLock(layout):
        state = load_state(layout)
        if release_id not in (state.get("installed") or {}):
            raise TransactionError("Releasen er ikke staged")
        if _read_active_release_id(layout) is not None:
            raise TransactionError("Fresh install må ikke have en aktiv release før godkendelsesporten")
        release_root = layout.releases / release_id
        units = _apply_definitions(layout, release_root, kiosk_user=kiosk_user)
        if layout.root == Path("/"):
            _run(["/usr/bin/systemd-sysusers", str(layout.sysusers_file)])
            _run(["/usr/bin/systemd-tmpfiles", "--create", str(layout.tmpfiles_file)])
            _run(["/usr/bin/systemctl", "daemon-reload"])
            _quiesce_runtime(layout)
            _disable_target(layout)
        _append_history(state, "definitions_installed_inactive", release_id=release_id, unit_count=len(units))
        save_state(layout, state)
        return {"status": "installed_inactive", "release_id": release_id, "units": units}
