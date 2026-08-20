#!/usr/bin/env python3
"""Fetch an untrusted runtime-input transport over HTTPS and pin its exact bytes."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 512 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_url(url: str, *, initial: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Runtime-input transport URL must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Runtime-input transport URL must not contain credentials or fragments")
    if initial and parsed.query:
        raise ValueError("Runtime-input workflow input must not contain a query string")


class _HttpsOnlyRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _validate_url(newurl, initial=False)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, expected_sha256: str, output: Path) -> tuple[int, str]:
    _validate_url(url, initial=True)
    if not SHA_RE.fullmatch(expected_sha256):
        raise ValueError("Expected runtime-input transport SHA-256 is invalid")
    output = output.resolve()
    if output.exists():
        raise ValueError("Runtime-input transport output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)

    opener = build_opener(_HttpsOnlyRedirects())
    request = Request(url, headers={"User-Agent": "ClientFlow-Release-Build/1"})
    h = hashlib.sha256()
    size = 0
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        with opener.open(request, timeout=60) as response, os.fdopen(fd, "wb", closefd=True) as out:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > MAX_BYTES:
                raise ValueError("Runtime-input transport exceeds maximum size")
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Runtime-input transport exceeds maximum size")
                h.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        output.unlink(missing_ok=True)
        raise

    actual = h.hexdigest()
    if actual != expected_sha256:
        output.unlink(missing_ok=True)
        raise ValueError("Runtime-input transport SHA-256 mismatch")
    st = output.stat()
    if not stat.S_ISREG(st.st_mode):
        output.unlink(missing_ok=True)
        raise ValueError("Runtime-input transport output is not a regular file")
    return size, actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    size, digest = fetch(args.url, args.expected_sha256, args.output)
    print(f"runtime_inputs_transport_size={size}")
    print(f"runtime_inputs_transport_sha256={digest}")
    print("RESULT: RUNTIME INPUT TRANSPORT VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
