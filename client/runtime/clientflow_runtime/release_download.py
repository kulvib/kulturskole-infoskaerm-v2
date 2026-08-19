"""Bounded same-origin download for approved keyless ClientFlow release bundles."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import ssl
import stat
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from .config import DomainCredential
from .net import DomainTransport

_RELEASE_ID_RE = re.compile(r"^clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_RELEASE_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_PATH_PREFIXES = ("/api/clientflow/release-artifacts/",)


class ReleaseDownloadError(RuntimeError):
    pass


def _state_root() -> Path:
    configured = os.getenv("STATE_DIRECTORY")
    base = Path(configured.split(":", 1)[0]) if configured else Path("/var/lib/clientflow/system-agent")
    if not base.is_absolute():
        raise ReleaseDownloadError("STATE_DIRECTORY skal være en absolut sti")
    return base / "incoming"


def _ensure_state_root() -> Path:
    root = _state_root()
    base = root.parent
    try:
        base_metadata = base.lstat()
    except FileNotFoundError as exc:
        raise ReleaseDownloadError("Systemagentens StateDirectory findes ikke") from exc
    if (
        stat.S_ISLNK(base_metadata.st_mode)
        or not stat.S_ISDIR(base_metadata.st_mode)
        or base_metadata.st_mode & 0o077
    ):
        raise ReleaseDownloadError("Systemagentens StateDirectory er usikker")
    base_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.mkdir(root.name, mode=0o700, dir_fd=base_fd)
        except FileExistsError:
            pass
        root_metadata = os.stat(root.name, dir_fd=base_fd, follow_symlinks=False)
        if (
            stat.S_ISLNK(root_metadata.st_mode)
            or not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_mode & 0o077
        ):
            raise ReleaseDownloadError("Release-downloadkataloget er usikkert")
        os.chmod(root.name, 0o700, dir_fd=base_fd, follow_symlinks=False)
        os.fsync(base_fd)
    finally:
        os.close(base_fd)
    return root


def _validate_url(credential: DomainCredential, raw: str, *, release_id: str) -> str:
    candidate = str(raw or "").strip()
    if candidate.startswith("/"):
        candidate = urljoin(credential.backend_url + "/", candidate.lstrip("/"))
    parsed = urlparse(candidate)
    base = urlparse(credential.backend_url)
    if (
        parsed.scheme != "https"
        or parsed.scheme != base.scheme
        or parsed.hostname != base.hostname
        or parsed.port != base.port
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or parsed.path != f"{ALLOWED_PATH_PREFIXES[0]}{release_id}"
    ):
        raise ReleaseDownloadError("Release-URL skal være en tilladt HTTPS-sti på backendens egen origin")
    return candidate


def _secure_existing(path: Path, *, expected_size: int, expected_sha: str) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise ReleaseDownloadError("Eksisterende releasefil har usikre rettigheder")
    if metadata.st_size != expected_size:
        return False
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest() == expected_sha


def download_release_bundle(
    transport: DomainTransport,
    payload: dict,
) -> Path:
    release_id = str(payload.get("release_id") or "")
    expected_sha = str(payload.get("bundle_sha256") or "")
    try:
        expected_size = int(payload.get("bundle_size"))
    except (TypeError, ValueError) as exc:
        raise ReleaseDownloadError("bundle_size er ugyldig") from exc
    if not _RELEASE_ID_RE.fullmatch(release_id) or not _SHA_RE.fullmatch(expected_sha):
        raise ReleaseDownloadError("Releaseidentitet eller SHA-256 er ugyldig")
    if not 1 <= expected_size <= MAX_RELEASE_BYTES:
        raise ReleaseDownloadError("Releasebundlens størrelse er ugyldig")
    url = _validate_url(transport.credential, str(payload.get("bundle_url") or ""), release_id=release_id)
    root = _ensure_state_root()
    destination = root / f"{release_id}.tar"
    if _secure_existing(destination, expected_size=expected_size, expected_sha=expected_sha):
        return destination

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{release_id}.", suffix=".download", dir=root)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/octet-stream",
                "Authorization": f"Bearer {transport.access_token()}",
                "User-Agent": "ClientFlow/1.2.0 system-agent",
            },
        )
        context = ssl.create_default_context(cafile=transport.credential.tls_ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        digest = hashlib.sha256()
        received = 0
        try:
            with urllib.request.urlopen(request, timeout=60, context=context) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) != expected_size:
                    raise ReleaseDownloadError("HTTP Content-Length matcher ikke den godkendte størrelse")
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    descriptor = -1
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > expected_size or received > MAX_RELEASE_BYTES:
                            raise ReleaseDownloadError("Release-download overskred den godkendte størrelse")
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
        except urllib.error.HTTPError as exc:
            raise ReleaseDownloadError(f"Release-download blev afvist med HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ReleaseDownloadError(f"Release-download fejlede: {exc}") from exc
        if received != expected_size or digest.hexdigest() != expected_sha:
            raise ReleaseDownloadError("Downloadet release matcher ikke størrelse og SHA-256")
        os.replace(temporary, destination)
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
