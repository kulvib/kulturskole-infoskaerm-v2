#!/usr/bin/env python3
"""Read-only production smoke test for PlanIQ release readiness.

The script uses only Python's standard library, performs GET requests only, and
never prints response bodies or full response headers.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import socket
import ssl
import sys
import time
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ACCEPTED_REDIRECT_STATUS_CODES = frozenset({301, 302, 307, 308})
TITLE_RE = re.compile(r"<title(?:\s[^>]*)?>(.*?)</title>", re.IGNORECASE | re.DOTALL)
FULL_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class SmokeCheckError(RuntimeError):
    """A stable, user-safe production smoke failure."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


RequestFunction = Callable[[str, str, float], HttpResponse]
SleepFunction = Callable[[float], None]


def _default_request(method: str, url: str, timeout: float) -> HttpResponse:
    if method != "GET":
        raise SmokeCheckError("Kun read-only GET-kald er tilladt")

    opener = build_opener(_NoRedirectHandler())
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json, text/html;q=0.9, */*;q=0.1",
            "User-Agent": "PlanIQ-Production-Readiness/36A",
        },
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.status),
                headers=dict(response.headers.items()),
                body=response.read(),
                url=response.geturl(),
            )
    except HTTPError as exc:
        return HttpResponse(
            status=int(exc.code),
            headers=dict(exc.headers.items()) if exc.headers else {},
            body=exc.read(),
            url=exc.geturl(),
        )


def _normalise_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return str(value).strip()
    return ""


def _canonical_parts(url: str) -> tuple[str, str, str, str]:
    parts = urlsplit(url)
    return parts.scheme.casefold(), parts.netloc.casefold(), parts.path or "/", parts.query


def _normalise_sha(value: str, label: str) -> str:
    candidate = str(value).strip().lower()
    if not FULL_GIT_SHA_RE.fullmatch(candidate):
        raise ValueError(f"{label} skal være et fuldt 40-tegns Git SHA")
    return candidate


def _short_sha(value: str) -> str:
    return value[:12]


class ProductionReadinessChecker:
    def __init__(
        self,
        *,
        base_url: str,
        expected_product: str,
        expected_commit: str,
        retries: int = 3,
        retry_delay: float = 5.0,
        timeout: float = 10.0,
        request_fn: RequestFunction = _default_request,
        sleep_fn: SleepFunction = time.sleep,
        output: Callable[[str], None] = print,
    ) -> None:
        self.base_url = self._validate_base_url(base_url)
        self.expected_product = expected_product.strip()
        if not self.expected_product:
            raise ValueError("--expected-product må ikke være tom")
        self.expected_commit = _normalise_sha(expected_commit, "--expected-commit")
        if retries < 1:
            raise ValueError("--retries skal være mindst 1")
        if retry_delay < 0:
            raise ValueError("--retry-delay må ikke være negativ")
        if timeout <= 0:
            raise ValueError("--timeout skal være større end 0")

        self.retries = retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.request_fn = request_fn
        self.sleep_fn = sleep_fn
        self.output = output
        self.request_ids: list[str] = []

    @staticmethod
    def _validate_base_url(value: str) -> str:
        candidate = value.strip().rstrip("/")
        parts = urlsplit(candidate)
        if parts.scheme.casefold() != "https":
            raise ValueError("--base-url skal bruge HTTPS")
        if not parts.hostname or parts.username is not None or parts.password is not None:
            raise ValueError("--base-url skal være et HTTPS-domæne uden credentials")
        if parts.query or parts.fragment:
            raise ValueError("--base-url må ikke indeholde query eller fragment")
        if parts.path not in ("", "/"):
            raise ValueError("--base-url må ikke indeholde en sti")
        return urlunsplit(("https", parts.netloc, "", "", ""))

    def _url(self, path: str, *, scheme: str = "https") -> str:
        parts = urlsplit(self.base_url)
        return urlunsplit((scheme, parts.netloc, path, "", ""))

    def _request_with_retries(self, url: str) -> tuple[HttpResponse, int]:
        last_network_error: BaseException | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.request_fn("GET", url, self.timeout)
            except (TimeoutError, socket.timeout, URLError, ssl.SSLError, ConnectionError) as exc:
                last_network_error = exc
                if attempt == self.retries:
                    break
                self.output(f"RETRY: netværksfejl ved {urlsplit(url).path or '/'}; forsøg {attempt + 1}/{self.retries}")
                self.sleep_fn(self.retry_delay)
                continue

            if response.status in RETRYABLE_STATUS_CODES and attempt < self.retries:
                self.output(
                    f"RETRY: {urlsplit(url).path or '/'} returnerede HTTP {response.status}; "
                    f"forsøg {attempt + 1}/{self.retries}"
                )
                self.sleep_fn(self.retry_delay)
                continue
            return response, attempt

        error_type = type(last_network_error).__name__ if last_network_error else "NetworkError"
        raise SmokeCheckError(
            f"{urlsplit(url).path or '/'} kunne ikke nås efter {self.retries} forsøg ({error_type})"
        )

    @staticmethod
    def _require_same_target(response: HttpResponse, expected_url: str) -> None:
        if _canonical_parts(response.url) != _canonical_parts(expected_url):
            raise SmokeCheckError("HTTPS-kald blev viderestillet væk fra det kanoniske endpoint")

    @staticmethod
    def _require_json(response: HttpResponse, path: str) -> object:
        content_type = _header(response.headers, "Content-Type").casefold()
        if not content_type.startswith("application/json"):
            raise SmokeCheckError(f"{path} har ikke Content-Type application/json")
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SmokeCheckError(f"{path} returnerede ugyldig JSON") from None

    @staticmethod
    def _require_no_store(response: HttpResponse, path: str) -> None:
        directives = {
            item.strip().casefold()
            for item in _header(response.headers, "Cache-Control").split(",")
            if item.strip()
        }
        if "no-store" not in directives:
            raise SmokeCheckError(f"{path} mangler Cache-Control no-store")

    def check_http_redirect(self) -> None:
        source_url = self._url("/", scheme="http")
        response, _ = self._request_with_retries(source_url)
        if response.status not in ACCEPTED_REDIRECT_STATUS_CODES:
            raise SmokeCheckError(f"HTTP-root returnerede HTTP {response.status} i stedet for HTTPS-redirect")
        location = _header(response.headers, "Location")
        if not location:
            raise SmokeCheckError("HTTP-root mangler Location-header")
        expected_url = self._url("/")
        if _canonical_parts(location) != _canonical_parts(expected_url):
            raise SmokeCheckError("HTTP-redirect bevarer ikke korrekt HTTPS-host og sti")
        self.output("OK: HTTP viderestiller sikkert til kanonisk HTTPS")

    def check_frontend(self) -> None:
        url = self._url("/")
        response, attempts = self._request_with_retries(url)
        self._require_same_target(response, url)
        if response.status != 200:
            raise SmokeCheckError(f"Frontend-root returnerede HTTP {response.status} efter {attempts} forsøg")
        content_type = _header(response.headers, "Content-Type").casefold()
        if not content_type.startswith("text/html"):
            raise SmokeCheckError("Frontend-root har ikke Content-Type text/html")
        html = response.body.decode("utf-8", errors="replace")
        match = TITLE_RE.search(html)
        if not match:
            raise SmokeCheckError("Frontend-root mangler et gyldigt title-element")
        actual_title = _normalise_text(match.group(1))
        if actual_title != _normalise_text(self.expected_product):
            raise SmokeCheckError("Frontendens title matcher ikke det forventede produkt")
        self.output(f"OK: Frontend-shell for {self.expected_product}")

    def _read_release_payload(self, path: str, expected_component: str) -> tuple[str, HttpResponse, int]:
        url = self._url(path)
        response, attempts = self._request_with_retries(url)
        self._require_same_target(response, url)
        if response.status != 200:
            request_id = _header(response.headers, "X-Request-ID")
            suffix = f"; request_id={request_id}" if request_id else ""
            raise SmokeCheckError(f"{path} returnerede HTTP {response.status} efter {attempts} forsøg{suffix}")
        payload = self._require_json(response, path)
        if not isinstance(payload, dict) or set(payload) != {"product", "component", "commit"}:
            raise SmokeCheckError(f"{path} afviger fra releaseidentitetskontrakten")
        if payload.get("product") != self.expected_product:
            raise SmokeCheckError(f"{path} har forkert produkt")
        if payload.get("component") != expected_component:
            raise SmokeCheckError(f"{path} har forkert komponent")
        try:
            commit = _normalise_sha(str(payload.get("commit", "")), f"{path} commit")
        except ValueError as exc:
            raise SmokeCheckError(str(exc)) from None
        self._require_no_store(response, path)
        return commit, response, attempts

    def check_release_identity(self) -> None:
        frontend_commit, _, frontend_attempts = self._read_release_payload(
            "/release.json", "frontend"
        )
        backend_commit, backend_response, backend_attempts = self._read_release_payload(
            "/version", "backend"
        )
        request_id = _header(backend_response.headers, "X-Request-ID")
        if not request_id:
            raise SmokeCheckError("/version mangler X-Request-ID")
        self.request_ids.append(request_id)

        if frontend_commit != backend_commit or frontend_commit != self.expected_commit:
            raise SmokeCheckError(
                "Production kører ikke den forventede commit "
                f"(forventet={_short_sha(self.expected_commit)}, "
                f"frontend={_short_sha(frontend_commit)}, "
                f"backend={_short_sha(backend_commit)})"
            )
        retry_note = max(frontend_attempts, backend_attempts)
        suffix = f" efter op til {retry_note} forsøg" if retry_note > 1 else ""
        self.output(f"OK: Frontend og backend kører commit {_short_sha(self.expected_commit)}{suffix}")

    def check_health_endpoint(self, path: str) -> None:
        url = self._url(path)
        for call_number in (1, 2):
            response, attempts = self._request_with_retries(url)
            self._require_same_target(response, url)
            if response.status != 200:
                request_id = _header(response.headers, "X-Request-ID")
                suffix = f"; request_id={request_id}" if request_id else ""
                raise SmokeCheckError(
                    f"{path} returnerede HTTP {response.status} efter {attempts} forsøg{suffix}"
                )
            payload = self._require_json(response, path)
            if payload != {"status": "ok"}:
                raise SmokeCheckError(f"{path} afviger fra den låste JSON-kontrakt")
            request_id = _header(response.headers, "X-Request-ID")
            if not request_id:
                raise SmokeCheckError(f"{path} mangler X-Request-ID")
            self.request_ids.append(request_id)
            retry_note = f" efter {attempts} forsøg" if attempts > 1 else ""
            self.output(f"OK: {path} kald {call_number}{retry_note}")

    def check_request_id_uniqueness(self) -> None:
        if len(self.request_ids) != 5 or len(set(self.request_ids)) != 5:
            raise SmokeCheckError("Release- og health-kaldene returnerede ikke fem unikke request-id'er")
        self.output("OK: Fem unikke X-Request-ID-værdier")

    def run(self) -> None:
        self.check_http_redirect()
        self.check_frontend()
        self.check_release_identity()
        self.check_health_endpoint("/health")
        self.check_health_endpoint("/health/db")
        self.check_request_id_uniqueness()
        self.output("PRODUCTION READINESS: OK")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Step 36A production smoke test")
    parser.add_argument("--base-url", required=True, help="Kanonisk HTTPS-base-URL")
    parser.add_argument("--expected-product", required=True, help="Forventet produktnavn")
    parser.add_argument("--expected-commit", required=True, help="Forventet fuldt Git SHA")
    parser.add_argument("--retries", type=int, default=3, help="Antal forsøg ved transiente fejl")
    parser.add_argument("--retry-delay", type=float, default=5.0, help="Sekunder mellem retries")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout pr. HTTP-kald")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        checker = ProductionReadinessChecker(
            base_url=args.base_url,
            expected_product=args.expected_product,
            expected_commit=args.expected_commit,
            retries=args.retries,
            retry_delay=args.retry_delay,
            timeout=args.timeout,
        )
        checker.run()
    except ValueError as exc:
        print(f"FEJL: {exc}", file=sys.stderr)
        return 2
    except SmokeCheckError as exc:
        print(f"FEJL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
