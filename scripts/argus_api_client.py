"""Stdlib client for the Argus operator session/operation API.

The session and CSRF cookies live in memory only. Credentials are sent once in
a JSON body and are never stored, logged, or placed in exceptions.
"""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request
import uuid
from http.cookies import SimpleCookie
from typing import Any, Callable, NamedTuple
from urllib.parse import quote, urlsplit

SESSION_COOKIE = "argus_session"
CSRF_COOKIE = "argus_csrf"
MAX_RESPONSE_BYTES = 1 << 20
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
TERMINAL_STATES = frozenset({"succeeded", "failed", "rolled-back", "denied", "expired", "indeterminate"})


class ApiUnavailable(Exception):
    """The API could not be reached or answered unusably; carries no payload."""


class ApiResponse(NamedTuple):
    status: int
    body: dict[str, Any]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def normalize_base_url(url: str) -> str:
    """Return the exact scheme://host[:port] origin; plain http only for loopback."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError as exc:
        raise ValueError("base URL is malformed") from exc
    if (
        parts.scheme not in {"https", "http"}
        or not host
        or parts.username
        or parts.path.strip("/")
        or parts.query
        or parts.fragment
        or (parts.scheme == "http" and host not in LOOPBACK_HOSTS)
    ):
        raise ValueError("base URL must be an https origin (http only for loopback)")
    return f"{parts.scheme}://{parts.netloc}"


class ApiClient:
    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self.origin = normalize_base_url(base_url)
        self._timeout = timeout
        self._cookies: dict[str, str] = {}
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> ApiResponse:
        send = {"Accept": "application/json", "Origin": self.origin, **(headers or {})}
        if self._cookies:
            send["Cookie"] = "; ".join(f"{name}={value}" for name, value in self._cookies.items())
        data = None
        if method == "POST":
            send["Content-Type"] = "application/json"
            if CSRF_COOKIE in self._cookies:
                send["X-Argus-CSRF"] = self._cookies[CSRF_COOKIE]
            data = json.dumps(body or {}).encode()
        request = urllib.request.Request(self.origin + path, data=data, headers=send, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                return self._finish(response.status, response)
        except urllib.error.HTTPError as exc:
            with exc:
                return self._finish(exc.code, exc)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # Only the exception type is kept: reprs may embed request details.
            raise ApiUnavailable(f"API request failed: {type(exc).__name__}") from None

    def _finish(self, status: int, response: Any) -> ApiResponse:
        for header in response.headers.get_all("Set-Cookie") or []:
            jar: SimpleCookie = SimpleCookie()
            try:
                jar.load(header)
            except Exception:  # noqa: BLE001 - a malformed cookie is ignored, never fatal
                continue
            for name, morsel in jar.items():
                if name not in {SESSION_COOKIE, CSRF_COOKIE}:
                    continue
                if morsel["max-age"] == "0" or not morsel.value:
                    self._cookies.pop(name, None)
                else:
                    self._cookies[name] = morsel.value
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ApiUnavailable("API response exceeded the size limit")
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {}
        return ApiResponse(status, parsed if isinstance(parsed, dict) else {})

    def exchange(self, bootstrap_token: str) -> ApiResponse:
        return self.request(
            "POST",
            "/api/session/exchange",
            {"bootstrapToken": bootstrap_token},
            headers={"X-Argus-CSRF-Bootstrap": secrets.token_urlsafe(32)},
        )

    def step_up(self, bootstrap_token: str) -> ApiResponse:
        return self.request("POST", "/api/session/step-up", {"bootstrapToken": bootstrap_token})

    def preview(self, workload_id: str, operation_type: str, parameters: dict[str, Any]) -> ApiResponse:
        return self.request(
            "POST",
            f"/api/workloads/{quote(workload_id, safe='')}/operations/preview",
            {"operationType": operation_type, "parameters": parameters},
        )

    def create(
        self,
        workload_id: str,
        operation_type: str,
        parameters: dict[str, Any],
        preview: dict[str, Any],
        *,
        idempotency_key: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> ApiResponse:
        return self.request(
            "POST",
            f"/api/workloads/{quote(workload_id, safe='')}/operations",
            {
                "operationType": operation_type,
                "parameters": parameters,
                "previewDigest": preview.get("previewDigest"),
                "expectedRevision": preview.get("expectedRevision"),
                "policyVersion": preview.get("policyVersion"),
            },
            headers={"Idempotency-Key": idempotency_key()},
        )

    def approve(self, operation_id: str, confirmation: str) -> ApiResponse:
        return self.request("POST", f"/api/operations/{quote(operation_id, safe='')}/approve", {"confirmation": confirmation})

    def cancel(self, operation_id: str) -> ApiResponse:
        return self.request("POST", f"/api/operations/{quote(operation_id, safe='')}/cancel", {})

    def operation(self, operation_id: str) -> ApiResponse:
        return self.request("GET", f"/api/operations/{quote(operation_id, safe='')}")
