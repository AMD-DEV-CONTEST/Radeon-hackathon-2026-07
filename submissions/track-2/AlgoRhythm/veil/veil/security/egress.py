"""Hard egress guarantee.

VEIL makes zero outbound network calls. That claim is worth nothing as a
promise in a README, so it is enforced at the transport layer: every HTTP
request in this codebase goes through `guarded_async_client`, and any host
outside CONFIG.security.allowed_hosts raises before a socket is opened.

The startup self-test (`egress_self_test`) deliberately attempts an external
connection and reports that it was blocked. That result is rendered in the UI
during the demo — a judge should not have to take our word for it.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from veil.config import CONFIG


class EgressBlocked(RuntimeError):
    """Raised when code attempts to reach a host outside the allowlist."""


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_host(url: str) -> str:
    """Validate a URL against the allowlist. Returns the host on success.

    Both the literal allowlist and a loopback-address check are applied, so
    ::1 and 127.0.0.2 pass without needing to be enumerated, while anything
    routable fails regardless of how it is spelled.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip("[]")
    if not host:
        raise EgressBlocked(f"Refusing request with no host: {url!r}")
    if host in CONFIG.security.allowed_hosts or _is_loopback(host):
        return host
    raise EgressBlocked(
        f"Egress blocked: {host!r} is not in the allowlist "
        f"{CONFIG.security.allowed_hosts}. VEIL does not make outbound calls."
    )


class GuardedTransport(httpx.AsyncHTTPTransport):
    """Transport that refuses non-local requests.

    Enforcement lives here rather than in a wrapper function so that redirects,
    retries and any library that is handed this transport are all covered.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        check_host(str(request.url))
        return await super().handle_async_request(request)


def guarded_async_client(timeout: float = 60.0, **kwargs: Any) -> httpx.AsyncClient:
    """The only HTTP client constructor in VEIL."""
    return httpx.AsyncClient(
        transport=GuardedTransport(),
        timeout=timeout,
        follow_redirects=False,   # a redirect is an egress attempt
        trust_env=False,          # ignore HTTP_PROXY / HTTPS_PROXY entirely
        **kwargs,
    )


@dataclass
class SelfTestResult:
    blocked: bool
    probe_url: str
    detail: str

    def as_banner(self) -> str:
        mark = "PASS" if self.blocked else "FAIL"
        return f"[{mark}] egress self-test — {self.detail}"


async def egress_self_test(probe_url: str = "https://api.openai.com/v1/models") -> SelfTestResult:
    """Attempt an external call and confirm it is refused.

    Called on startup and exposed at /api/security/selftest so the guarantee is
    demonstrable rather than asserted.
    """
    try:
        async with guarded_async_client(timeout=3.0) as client:
            await client.get(probe_url)
    except EgressBlocked as exc:
        return SelfTestResult(True, probe_url, str(exc))
    except Exception as exc:  # noqa: BLE001 - any failure short of success is not a pass
        return SelfTestResult(
            False,
            probe_url,
            f"Request failed for an unexpected reason ({type(exc).__name__}); "
            "the allowlist did not fire and must be investigated.",
        )
    return SelfTestResult(
        False, probe_url, "External request SUCCEEDED — the egress guard is not active."
    )
