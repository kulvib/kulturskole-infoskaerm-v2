from __future__ import annotations

import base64
import json
from pathlib import Path

import jwt
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def test_cve_2026_101918_fixed_version_is_pinned_in_backend_and_runtime() -> None:
    backend = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8")
    runtime = (ROOT / "client/runtime/pyproject.toml").read_text(encoding="utf-8")
    lock = json.loads(
        (ROOT / "client/release/runtime-platform-inputs.lock.json").read_text(encoding="utf-8")
    )

    assert "PyJWT==2.15.1" in backend
    assert "PyJWT==2.15.1" in runtime
    pyjwt = [row for row in lock["artifacts"] if row["file"].startswith("pyjwt-")]
    assert pyjwt == [
        {
            "file": "pyjwt-2.15.1-py3-none-any.whl",
            "sha256": "42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193",
            "size": 33860,
        }
    ]


def test_verify_signature_false_recursion_failure_is_wrapped_by_pyjwt() -> None:
    header = _b64url(b'{"alg":"none","typ":"JWT"}')
    payload = _b64url(b'{"nested":' + (b"[" * 10000) + b"0" + (b"]" * 10000) + b"}")
    token = f"{header}.{payload}."

    with pytest.raises(jwt.PyJWTError):
        jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
