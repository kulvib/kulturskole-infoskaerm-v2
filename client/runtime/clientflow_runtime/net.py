"""Authenticated HTTP and WebSocket transport for one ClientFlow domain."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import ssl
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import jwt

from .config import DomainCredential
from .constants import AGENT_VERSION, DEFAULT_HTTP_TIMEOUT


class TransportError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(slots=True)
class TokenState:
    value: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> dict[str, Any]:
        value = json.loads(self.body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("HTTP-responsen skal være et JSON-objekt")
        return value


class DomainTransport:
    def __init__(self, credential: DomainCredential) -> None:
        self.credential = credential
        self._token: TokenState | None = None
        self._token_lock = threading.Lock()
        self._ssl_context = ssl.create_default_context(cafile=credential.tls_ca_file)
        self._ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    def _token_is_valid(self) -> bool:
        return bool(
            self._token
            and self._token.expires_at > datetime.now(timezone.utc) + timedelta(seconds=30)
        )

    def _raw_request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        request = Request(url=url, data=body, method=method.upper(), headers=headers)
        try:
            with urlopen(request, timeout=timeout, context=self._ssl_context) as response:
                return HttpResponse(
                    status_code=int(response.status),
                    body=response.read(),
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except HTTPError as exc:
            return HttpResponse(
                status_code=int(exc.code),
                body=exc.read(),
                headers={key.lower(): value for key, value in exc.headers.items()},
            )
        except (OSError, URLError, TimeoutError) as exc:
            raise TransportError(f"HTTP-transport fejlede: {exc}", retryable=True) from exc

    def access_token(self, *, force_refresh: bool = False) -> str:
        with self._token_lock:
            if not force_refresh and self._token_is_valid():
                return self._token.value
            body = json.dumps(
                {
                    "client_id": self.credential.client_id,
                    "credential_id": self.credential.credential_id,
                    "domain": self.credential.domain.value,
                    "client_secret": self.credential.client_secret,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            response = self._raw_request(
                "POST",
                f"{self.credential.backend_url}/api/client-auth/token",
                body=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": f"ClientFlow/{AGENT_VERSION} {self.credential.domain.value}-agent",
                },
                timeout=DEFAULT_HTTP_TIMEOUT,
            )
            if response.status_code != 200:
                raise TransportError(
                    f"Domænetoken blev afvist med HTTP {response.status_code}",
                    status_code=response.status_code,
                    retryable=response.status_code >= 500 or response.status_code == 429,
                )
            try:
                payload = response.json()
                token = str(payload["access_token"])
                claims = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
                expected_audience = f"clientflow-domain:{self.credential.domain.value}"
                audience = claims.get("aud")
                audiences = (
                    {str(audience)}
                    if isinstance(audience, str)
                    else {str(item) for item in audience or []}
                )
                expected_scope = f"clientflow:{self.credential.domain.value}"
                expected_sub = f"client:{self.credential.client_id}:{self.credential.credential_id}"
                now = datetime.now(timezone.utc)
                expires_at = datetime.fromtimestamp(float(claims["exp"]), tz=timezone.utc)
                issued_at = datetime.fromtimestamp(float(claims["iat"]), tz=timezone.utc)
                not_before = datetime.fromtimestamp(float(claims["nbf"]), tz=timezone.utc)
                if (
                    payload.get("client_id") != self.credential.client_id
                    or str(payload.get("credential_id") or "") != self.credential.credential_id
                    or str(payload.get("domain") or "") != self.credential.domain.value
                    or str(payload.get("audience") or "") != expected_audience
                    or str(payload.get("scope") or "") != expected_scope
                    or str(payload.get("issuer") or "") != self.credential.token_issuer
                    or str(claims.get("iss") or "") != self.credential.token_issuer
                    or int(payload.get("token_version", -1)) != int(claims.get("token_version", -2))
                    or claims.get("sub") != expected_sub
                    or claims.get("principal") != "client_domain"
                    or int(claims.get("client_id", 0)) != self.credential.client_id
                    or str(claims.get("credential_id") or "") != self.credential.credential_id
                    or claims.get("domain") != self.credential.domain.value
                    or claims.get("scope") != expected_scope
                    or expected_audience not in audiences
                    or not str(claims.get("jti") or "")
                    or issued_at > now + timedelta(seconds=10)
                    or not_before > now + timedelta(seconds=10)
                    or expires_at <= now
                ):
                    raise ValueError("Domænetokenets binding matcher ikke credentialet")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, jwt.PyJWTError) as exc:
                raise TransportError("Backend returnerede et ugyldigt domænetoken", retryable=False) from exc
            self._token = TokenState(token, expires_at)
            return token

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
        timeout: float = DEFAULT_HTTP_TIMEOUT,
    ) -> HttpResponse:
        if json_body is not None and data is not None:
            raise ValueError("HTTP-request kan ikke have både JSON og rå bytes")
        body = data
        merged_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token()}",
            "User-Agent": f"ClientFlow/{AGENT_VERSION} {self.credential.domain.value}-agent",
        }
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            merged_headers["Content-Type"] = "application/json"
        if headers:
            merged_headers.update(headers)
        url = f"{self.credential.backend_url}{path}"
        response = self._raw_request(method, url, body=body, headers=merged_headers, timeout=timeout)
        if response.status_code == 401:
            merged_headers["Authorization"] = f"Bearer {self.access_token(force_refresh=True)}"
            response = self._raw_request(method, url, body=body, headers=merged_headers, timeout=timeout)
        if response.status_code not in expected:
            detail = ""
            try:
                response_body = response.json()
                detail = str(response_body.get("detail") or response_body.get("error") or "")
            except (ValueError, json.JSONDecodeError):
                detail = response.text[:500]
            retryable = response.status_code >= 500 or response.status_code in {408, 409, 425, 429}
            raise TransportError(
                f"HTTP {response.status_code} for {path}: {detail}".strip(),
                status_code=response.status_code,
                retryable=retryable,
            )
        return response

    def json_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.request(method, path, **kwargs)
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise TransportError("Backend returnerede ugyldig JSON", retryable=False) from exc

    def websocket_url(self, path: str) -> str:
        parsed = urlparse(self.credential.backend_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))

    def websocket_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "User-Agent": f"ClientFlow/{AGENT_VERSION} {self.credential.domain.value}-agent",
        }


def backoff_seconds(attempt: int) -> float:
    return min(60.0, 1.0 * (2 ** min(max(attempt, 0), 6)))


def utc_epoch() -> float:
    return time.time()
