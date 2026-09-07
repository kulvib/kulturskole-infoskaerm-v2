from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("RATE_LIMIT_NAMESPACE", "planiq-ci")
os.environ.setdefault("RATE_LIMIT_REDIS_REQUIRED", "false")

from starlette.requests import Request

from service1.client_ip import get_client_ip
from service1.observability import bind_request_id, reset_request_id
from service1.rate_limit import (
    RateLimitExceeded,
    _memory_windows,
    _reset_rate_limit_state_for_tests,
    _storage_key,
    assert_key_not_limited,
    clear_key_rate_limit,
    enforce_key_rate_limit,
    normalize_rate_limit_identifier,
    rate_limit_exception_handler,
    record_key_attempt,
)


def _request(*, forwarded_for: str | None = None, client: tuple[str, int] = ("127.0.0.1", 1234)) -> Request:
    headers = [(b"host", b"testserver"), (b"x-request-id", b"ci-rate-limit")]
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/users/login",
        "raw_path": b"/api/users/login",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": client,
        "server": ("testserver", 443),
    }
    return Request(scope)


class ClientIpContractTests(unittest.TestCase):
    def test_render_forwarded_for_uses_first_valid_address(self) -> None:
        request = _request(forwarded_for="203.0.113.7, 198.51.100.9")
        self.assertEqual(get_client_ip(request), "203.0.113.7")

    def test_invalid_forwarded_for_falls_back_to_socket_peer(self) -> None:
        request = _request(forwarded_for="not-an-ip", client=("192.0.2.10", 1234))
        self.assertEqual(get_client_ip(request), "192.0.2.10")


class RateLimitStorageContractTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_rate_limit_state_for_tests()

    def test_limit_allows_configured_attempts_then_rejects(self) -> None:
        with patch("service1.rate_limit._redis_client", None):
            enforce_key_rate_limit(bucket="login", key="203.0.113.7", max_attempts=2, window_seconds=60)
            enforce_key_rate_limit(bucket="login", key="203.0.113.7", max_attempts=2, window_seconds=60)
            with self.assertRaises(RateLimitExceeded) as raised:
                enforce_key_rate_limit(bucket="login", key="203.0.113.7", max_attempts=2, window_seconds=60)
        self.assertEqual(raised.exception.bucket, "login")
        self.assertGreaterEqual(raised.exception.retry_after, 1)

    def test_failed_account_bucket_is_checked_and_can_be_cleared(self) -> None:
        key = normalize_rate_limit_identifier(" User@Example.COM ")
        self.assertEqual(key, "user@example.com")
        with patch("service1.rate_limit._redis_client", None):
            record_key_attempt(bucket="auth-login-account", key=key, window_seconds=60)
            with self.assertRaises(RateLimitExceeded):
                assert_key_not_limited(
                    bucket="auth-login-account",
                    key=key,
                    max_attempts=1,
                    window_seconds=60,
                )
            clear_key_rate_limit(bucket="auth-login-account", key=key)
            assert_key_not_limited(
                bucket="auth-login-account",
                key=key,
                max_attempts=1,
                window_seconds=60,
            )

    def test_storage_key_never_contains_raw_identifier(self) -> None:
        raw = "person@example.com"
        key = _storage_key("auth-login-account", raw)
        self.assertNotIn(raw, key)
        self.assertIn("auth-login-account", key)

    def test_required_redis_never_falls_back_to_process_memory(self) -> None:
        broken_redis = Mock()
        broken_redis.eval.side_effect = ConnectionError("redis unavailable")
        with (
            patch("service1.rate_limit._redis_client", broken_redis),
            patch("service1.rate_limit.RATE_LIMIT_REDIS_REQUIRED", True),
        ):
            with self.assertRaises(RuntimeError):
                enforce_key_rate_limit(
                    bucket="login",
                    key="203.0.113.7",
                    max_attempts=2,
                    window_seconds=60,
                )

    def test_memory_fallback_has_a_bounded_number_of_keys(self) -> None:
        with (
            patch("service1.rate_limit._redis_client", None),
            patch("service1.rate_limit.RATE_LIMIT_MEMORY_MAX_KEYS", 2),
        ):
            for index in range(5):
                enforce_key_rate_limit(
                    bucket="login",
                    key=f"203.0.113.{index}",
                    max_attempts=2,
                    window_seconds=60,
                )
        self.assertLessEqual(len(_memory_windows), 2)



class RateLimitResponseContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_429_response_has_common_body_and_headers(self) -> None:
        request = _request()
        _, token = bind_request_id(request)
        try:
            response = await rate_limit_exception_handler(
                request,
                RateLimitExceeded(bucket="auth-login-ip", retry_after=42, detail="Prøv igen senere."),
            )
        finally:
            reset_request_id(token)
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("retry-after"), "42")
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("x-request-id"), "ci-rate-limit")
        self.assertEqual(payload["error"], "rate_limit_exceeded")
        self.assertEqual(payload["retry_after"], 42)
        self.assertEqual(payload["request_id"], "ci-rate-limit")
