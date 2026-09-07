from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("PASSWORD_RESET_FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")
os.environ.setdefault("HLS_BASE_DIR", "/tmp/planiq-display-ci-hls")

from service1.main import app
from service1.release_identity import (
    ReleaseIdentityUnavailable,
    build_release_identity,
    resolve_release_commit,
)


async def _asgi_get(path: str, *, request_id: str = "ci-release-id") -> tuple[int, dict[str, str], bytes]:
    headers = [
        (b"host", b"testserver"),
        (b"x-request-id", request_id.encode("ascii")),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    request_delivered = False
    wait_forever = asyncio.Event()
    messages: list[dict] = []

    async def receive() -> dict:
        nonlocal request_delivered
        if not request_delivered:
            request_delivered = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await wait_forever.wait()
        raise AssertionError("unreachable")

    async def send(message: dict) -> None:
        messages.append(message)

    try:
        await app(scope, receive, send)
    except Exception:
        if not any(message.get("type") == "http.response.start" for message in messages):
            raise

    start = next(message for message in messages if message.get("type") == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message.get("type") == "http.response.body"
    )
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    return int(start["status"]), response_headers, body


class ReleaseIdentityUnitTests(unittest.TestCase):
    def test_valid_render_sha_is_normalised_to_lowercase(self) -> None:
        sha = "ABCDEF0123456789ABCDEF0123456789ABCDEF01"
        self.assertEqual(
            resolve_release_commit({"RENDER_GIT_COMMIT": sha}),
            sha.lower(),
        )

    def test_payload_is_stable_and_exact(self) -> None:
        sha = "a" * 40
        self.assertEqual(
            build_release_identity("PlanIQ Display", environment={"RENDER_GIT_COMMIT": sha}),
            {"product": "PlanIQ Display", "component": "backend", "commit": sha},
        )

    def test_missing_render_sha_is_rejected(self) -> None:
        with self.assertRaises(ReleaseIdentityUnavailable):
            resolve_release_commit({})

    def test_short_render_sha_is_rejected(self) -> None:
        with self.assertRaises(ReleaseIdentityUnavailable):
            resolve_release_commit({"RENDER_GIT_COMMIT": "abc123"})

    def test_non_hex_render_sha_is_rejected(self) -> None:
        with self.assertRaises(ReleaseIdentityUnavailable):
            resolve_release_commit({"RENDER_GIT_COMMIT": "z" * 40})


class ReleaseIdentityEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_version_returns_exact_release_contract(self) -> None:
        sha = "b" * 40
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": sha}, clear=False):
            status, headers, body = await _asgi_get("/version", request_id="ci-version-ok")

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-request-id"), "ci-version-ok")
        self.assertIn("no-store", headers.get("cache-control", ""))
        self.assertEqual(
            json.loads(body),
            {"product": "PlanIQ Display", "component": "backend", "commit": sha},
        )

    async def test_version_failure_is_neutral_and_correlated(self) -> None:
        secret_value = "database-secret-must-not-leak"
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": secret_value}, clear=False):
            status, headers, body = await _asgi_get("/version", request_id="ci-version-503")

        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("x-request-id"), "ci-version-503")
        self.assertIn("no-store", headers.get("cache-control", ""))
        self.assertEqual(payload["error"], "release_identity_unavailable")
        self.assertEqual(payload["request_id"], "ci-version-503")
        self.assertEqual(payload["status"], "unavailable")
        self.assertNotIn(secret_value, body.decode("utf-8"))

    async def test_version_never_uses_database(self) -> None:
        sha = "c" * 40
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": sha}, clear=False):
            with patch("service1.main.Session", side_effect=AssertionError("database used")):
                status, _, body = await _asgi_get("/version")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["commit"], sha)


if __name__ == "__main__":
    unittest.main()
