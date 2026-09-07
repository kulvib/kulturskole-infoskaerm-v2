from __future__ import annotations

from collections import deque
from pathlib import Path
import sys
import unittest
from urllib.error import URLError

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_production_readiness import (  # noqa: E402
    HttpResponse,
    ProductionReadinessChecker,
    SmokeCheckError,
)

EXPECTED_SHA = "a" * 40
OTHER_SHA = "b" * 40


class FakeTransport:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []

    def __call__(self, method, url, timeout):
        self.calls.append((method, url, timeout))
        if not self.responses:
            raise AssertionError(f"Uventet HTTP-kald: {method} {url}")
        item = self.responses.popleft()
        if isinstance(item, BaseException):
            raise item
        return item


def response(
    status=200,
    *,
    content_type="application/json",
    body=b'{"status":"ok"}',
    request_id="rid",
    url="https://example.test/health",
    location=None,
    cache_control=None,
):
    headers = {"Content-Type": content_type}
    if request_id is not None:
        headers["X-Request-ID"] = request_id
    if location is not None:
        headers["Location"] = location
    if cache_control is not None:
        headers["Cache-Control"] = cache_control
    return HttpResponse(status=status, headers=headers, body=body, url=url)


def release_response(path, component, *, commit=EXPECTED_SHA, product="PlanIQ Test", request_id=None, status=200, cache_control="no-store, max-age=0"):
    body = (
        f'{{"product":"{product}","component":"{component}","commit":"{commit}"}}'
    ).encode()
    return response(
        status,
        body=body,
        request_id=request_id,
        url=f"https://example.test{path}",
        cache_control=cache_control,
    )


def successful_sequence(base="https://example.test", title="PlanIQ Test"):
    return [
        response(301, content_type="text/html", body=b"", request_id=None, url="http://example.test/", location=f"{base}/"),
        response(200, content_type="text/html; charset=utf-8", body=f"<html><title>{title}</title></html>".encode(), request_id=None, url=f"{base}/"),
        release_response("/release.json", "frontend"),
        release_response("/version", "backend", request_id="v1"),
        response(request_id="h1", url=f"{base}/health"),
        response(request_id="h2", url=f"{base}/health"),
        response(request_id="d1", url=f"{base}/health/db"),
        response(request_id="d2", url=f"{base}/health/db"),
    ]


class ProductionReadinessCheckerTests(unittest.TestCase):
    def make_checker(self, responses, **overrides):
        transport = FakeTransport(responses)
        output = []
        checker = ProductionReadinessChecker(
            base_url=overrides.pop("base_url", "https://example.test"),
            expected_product=overrides.pop("expected_product", "PlanIQ Test"),
            expected_commit=overrides.pop("expected_commit", EXPECTED_SHA),
            retries=overrides.pop("retries", 3),
            retry_delay=0,
            timeout=10,
            request_fn=transport,
            sleep_fn=lambda _: None,
            output=output.append,
            **overrides,
        )
        return checker, transport, output

    def test_complete_contract_passes_and_uses_get_only(self):
        checker, transport, output = self.make_checker(successful_sequence())
        checker.run()
        self.assertEqual(len(transport.calls), 8)
        self.assertTrue(all(method == "GET" for method, _, _ in transport.calls))
        self.assertIn("PRODUCTION READINESS: OK", output)

    def test_transient_503_is_retried_then_succeeds(self):
        responses = successful_sequence()
        responses.insert(4, response(503, request_id="temporary", url="https://example.test/health"))
        checker, transport, output = self.make_checker(responses)
        checker.run()
        self.assertEqual(len(transport.calls), 9)
        self.assertTrue(any(line.startswith("RETRY:") for line in output))

    def test_transient_release_503_is_retried_then_succeeds(self):
        responses = successful_sequence()
        responses.insert(2, response(503, request_id=None, url="https://example.test/release.json"))
        checker, transport, output = self.make_checker(responses)
        checker.run()
        self.assertEqual(len(transport.calls), 9)
        self.assertTrue(any("/release.json" in line for line in output if line.startswith("RETRY:")))

    def test_repeated_503_fails_after_retries(self):
        responses = successful_sequence()[:4] + [
            response(503, url="https://example.test/health"),
            response(503, url="https://example.test/health"),
            response(503, url="https://example.test/health"),
        ]
        checker, transport, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "HTTP 503 efter 3 forsøg"):
            checker.run()
        self.assertEqual(len(transport.calls), 7)

    def test_missing_request_id_fails(self):
        responses = successful_sequence()
        responses[4] = response(request_id=None, url="https://example.test/health")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "mangler X-Request-ID"):
            checker.run()

    def test_missing_version_request_id_fails(self):
        responses = successful_sequence()
        responses[3] = release_response("/version", "backend", request_id=None)
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "/version mangler X-Request-ID"):
            checker.run()

    def test_reused_request_id_fails(self):
        responses = successful_sequence()
        responses[7] = response(request_id="v1", url="https://example.test/health/db")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "fem unikke request-id"):
            checker.run()

    def test_extra_json_content_fails(self):
        responses = successful_sequence()
        responses[4] = response(body=b'{"status":"ok","extra":true}', url="https://example.test/health")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "låste JSON-kontrakt"):
            checker.run()

    def test_wrong_health_content_type_fails(self):
        responses = successful_sequence()
        responses[4] = response(content_type="text/plain", url="https://example.test/health")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "Content-Type application/json"):
            checker.run()

    def test_wrong_frontend_product_fails(self):
        responses = successful_sequence(title="Et andet produkt")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "title matcher ikke"):
            checker.run()

    def test_foreign_https_redirect_fails(self):
        responses = successful_sequence()
        responses[1] = response(200, content_type="text/html", body=b"<title>PlanIQ Test</title>", request_id=None, url="https://foreign.example/")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "viderestillet væk"):
            checker.run()

    def test_non_https_base_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "skal bruge HTTPS"):
            ProductionReadinessChecker(base_url="http://example.test", expected_product="PlanIQ Test", expected_commit=EXPECTED_SHA)

    def test_invalid_expected_commit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "40-tegns Git SHA"):
            ProductionReadinessChecker(base_url="https://example.test", expected_product="PlanIQ Test", expected_commit="abc123")

    def test_network_timeout_is_retried_and_fails_safely(self):
        checker, transport, _ = self.make_checker([URLError("timeout"), URLError("timeout"), URLError("timeout")])
        with self.assertRaisesRegex(SmokeCheckError, "kunne ikke nås efter 3 forsøg"):
            checker.run()
        self.assertEqual(len(transport.calls), 3)

    def test_http_redirect_must_preserve_host_and_path(self):
        responses = successful_sequence()
        responses[0] = response(301, content_type="text/html", body=b"", request_id=None, url="http://example.test/", location="https://foreign.example/")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "bevarer ikke korrekt"):
            checker.run()

    def test_credentials_in_base_url_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "uden credentials"):
            ProductionReadinessChecker(base_url="https://user:password@example.test", expected_product="PlanIQ Test", expected_commit=EXPECTED_SHA)

    def test_frontend_commit_mismatch_fails(self):
        responses = successful_sequence()
        responses[2] = release_response("/release.json", "frontend", commit=OTHER_SHA)
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "Production kører ikke den forventede commit"):
            checker.run()

    def test_backend_is_current_but_frontend_is_stale_fails(self):
        responses = successful_sequence()
        # Backendens /version beholder EXPECTED_SHA, mens det statiske frontend-artefakt er gammelt.
        responses[2] = release_response("/release.json", "frontend", commit=OTHER_SHA)
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "Production kører ikke den forventede commit"):
            checker.run()

    def test_backend_commit_mismatch_fails(self):
        responses = successful_sequence()
        responses[3] = release_response("/version", "backend", commit=OTHER_SHA, request_id="v1")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "Production kører ikke den forventede commit"):
            checker.run()

    def test_both_commits_differ_from_expected_fails(self):
        responses = successful_sequence()
        responses[2] = release_response("/release.json", "frontend", commit=OTHER_SHA)
        responses[3] = release_response("/version", "backend", commit=OTHER_SHA, request_id="v1")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "forventet=aaaaaaaaaaaa"):
            checker.run()

    def test_invalid_release_sha_fails(self):
        responses = successful_sequence()
        responses[2] = release_response("/release.json", "frontend", commit="abc123")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "40-tegns Git SHA"):
            checker.run()

    def test_wrong_release_product_fails(self):
        responses = successful_sequence()
        responses[2] = release_response("/release.json", "frontend", product="Wrong Product")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "forkert produkt"):
            checker.run()

    def test_wrong_release_component_fails(self):
        responses = successful_sequence()
        responses[2] = release_response("/release.json", "backend")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "forkert komponent"):
            checker.run()

    def test_release_metadata_must_be_no_store(self):
        responses = successful_sequence()
        responses[2] = release_response("/release.json", "frontend", cache_control="public, max-age=60")
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "Cache-Control no-store"):
            checker.run()

    def test_release_payload_rejects_extra_fields(self):
        responses = successful_sequence()
        responses[2] = response(
            body=(f'{{"product":"PlanIQ Test","component":"frontend","commit":"{EXPECTED_SHA}","extra":true}}').encode(),
            request_id=None,
            url="https://example.test/release.json",
            cache_control="no-store",
        )
        checker, _, _ = self.make_checker(responses)
        with self.assertRaisesRegex(SmokeCheckError, "releaseidentitetskontrakten"):
            checker.run()


if __name__ == "__main__":
    unittest.main()
