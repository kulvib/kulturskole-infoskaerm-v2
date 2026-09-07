from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

# main.py validerer env ved import. CI-værdierne overskriver disse defaults.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("PASSWORD_RESET_FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")
os.environ.setdefault("HLS_BASE_DIR", "/tmp/planiq-display-ci-hls")

from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from service1.main import app
from service1.observability import REQUEST_ID_HEADER
from service1.schema_readiness import SchemaReadiness


async def _asgi_request(
    path: str,
    *,
    method: str = "GET",
    request_id: str | None = None,
    origin: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Kør en request direkte mod ASGI-appen uden startup eller database."""
    headers = [(b"host", b"testserver")]
    if request_id is not None:
        headers.append((REQUEST_ID_HEADER.lower().encode("ascii"), request_id.encode("ascii")))
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
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

    await app(scope, receive, send)

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


class ErrorContractTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        paths = {getattr(route, "path", None) for route in app.routes}

        if "/__ci__/unexpected-error" not in paths:
            async def unexpected_error() -> None:
                raise RuntimeError("sensitive-value-must-not-leak")

            app.add_api_route("/__ci__/unexpected-error", unexpected_error, methods=["GET"])

        if "/__ci__/database-timeout" not in paths:
            async def database_timeout() -> None:
                raise SQLAlchemyTimeoutError("database-url-must-not-leak")

            app.add_api_route("/__ci__/database-timeout", database_timeout, methods=["GET"])

    async def test_health_has_request_id_header(self) -> None:
        status, headers, body = await _asgi_request("/health", request_id="ci-health-123")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-request-id"), "ci-health-123")
        self.assertEqual(json.loads(body), {"status": "ok"})

    async def test_invalid_external_request_id_is_replaced(self) -> None:
        invalid_id = "x" * 80
        status, headers, _ = await _asgi_request("/health", request_id=invalid_id)
        self.assertEqual(status, 200)
        generated = headers.get("x-request-id", "")
        self.assertNotEqual(generated, invalid_id)
        self.assertRegex(generated, r"^[0-9a-f]{32}$")

    async def test_unexpected_error_is_neutral_and_correlated(self) -> None:
        status, headers, body = await _asgi_request(
            "/__ci__/unexpected-error",
            request_id="ci-error-500",
        )
        payload = json.loads(body)
        self.assertEqual(status, 500)
        self.assertEqual(headers.get("x-request-id"), "ci-error-500")
        self.assertEqual(payload["error"], "internal_server_error")
        self.assertEqual(payload["request_id"], "ci-error-500")
        self.assertNotIn("sensitive-value", body.decode("utf-8"))
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")

    async def test_database_pool_timeout_returns_503(self) -> None:
        status, headers, body = await _asgi_request(
            "/__ci__/database-timeout",
            request_id="ci-error-503",
        )
        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("x-request-id"), "ci-error-503")
        self.assertEqual(payload["error"], "database_unavailable")
        self.assertEqual(payload["request_id"], "ci-error-503")
        self.assertNotIn("database-url", body.decode("utf-8"))
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")

    async def test_database_health_failure_returns_neutral_503(self) -> None:
        class FailingSession:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def exec(self, _statement) -> None:
                raise RuntimeError("database-credential-must-not-leak")

        with patch("service1.main.Session", FailingSession):
            status, headers, body = await _asgi_request(
                "/health/db",
                request_id="ci-health-db-503",
            )

        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("x-request-id"), "ci-health-db-503")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error"], "database_unavailable")
        self.assertEqual(payload["request_id"], "ci-health-db-503")
        self.assertNotIn("database-credential", body.decode("utf-8"))


    async def test_health_does_not_use_database_or_schema_checker(self) -> None:
        with patch("service1.main.Session", side_effect=AssertionError("database used")):
            with patch(
                "service1.main.check_schema_readiness",
                side_effect=AssertionError("schema checker used"),
            ):
                status, headers, body = await _asgi_request(
                    "/health",
                    request_id="ci-liveness-only",
                )

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-request-id"), "ci-liveness-only")
        self.assertEqual(json.loads(body), {"status": "ok"})

    async def test_database_health_checks_connection_and_current_schema(self) -> None:
        class HealthySession:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def exec(self, _statement) -> None:
                return None

            def connection(self):
                return object()

        ready = SchemaReadiness(
            ready=True,
            reason="ready",
            repository_head_count=1,
            database_head_count=1,
        )
        with patch("service1.main.Session", HealthySession):
            with patch("service1.main.check_schema_readiness", return_value=ready) as checker:
                status, headers, body = await _asgi_request(
                    "/health/db",
                    request_id="ci-health-db-200",
                )

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-request-id"), "ci-health-db-200")
        self.assertEqual(json.loads(body), {"status": "ok"})
        checker.assert_called_once()

    async def test_database_schema_drift_returns_neutral_503(self) -> None:
        class HealthySession:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def exec(self, _statement) -> None:
                return None

            def connection(self):
                return object()

        not_ready = SchemaReadiness(
            ready=False,
            reason="database_revision_unknown",
            repository_head_count=1,
            database_head_count=1,
        )
        with patch("service1.main.Session", HealthySession):
            with patch("service1.main.check_schema_readiness", return_value=not_ready):
                with patch("service1.main.logger.warning") as warning:
                    status, headers, body = await _asgi_request(
                        "/health/db",
                        request_id="ci-schema-503",
                    )

        payload = json.loads(body)
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("x-request-id"), "ci-schema-503")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error"], "database_schema_not_ready")
        self.assertEqual(payload["detail"], "Databaseskemaet er ikke klar")
        self.assertEqual(payload["request_id"], "ci-schema-503")
        self.assertNotIn("revision_unknown", body.decode("utf-8"))
        warning.assert_called_once_with(
            "database_schema_not_ready request_id=%s reason=%s "
            "repository_head_count=%s database_head_count=%s",
            "ci-schema-503",
            "database_revision_unknown",
            1,
            1,
        )

    async def test_hls_preflight_keeps_cors_and_request_id(self) -> None:
        status, headers, body = await _asgi_request(
            "/hls/1/index.m3u8",
            method="OPTIONS",
            request_id="ci-hls-options",
            origin="http://localhost:5173",
        )
        self.assertEqual(status, 204)
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("x-request-id"), "ci-hls-options")
        self.assertEqual(headers.get("access-control-allow-origin"), "http://localhost:5173")
        self.assertIn("GET", headers.get("access-control-allow-methods", ""))


if __name__ == "__main__":
    unittest.main()
