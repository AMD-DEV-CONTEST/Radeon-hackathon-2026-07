"""Bounded Ollama localhost availability smoke.

Pings a localhost-only Ollama endpoint with a strict timeout. Refuses
any non-localhost host (network providers are blocked). Output is
always treated as untrusted. No repo/source input. No patch generation.
No corpus write. No training eligibility opened.

Design contract:
  - The caller passes ``endpoint``. If endpoint is empty the smoke
    returns BLOCKED_NOT_CONFIGURED — appropriate for the default case
    where Ollama is not in use.
  - Endpoint must resolve to ``127.0.0.1`` or ``localhost`` (case
    insensitive). Anything else returns BLOCKED_NOT_CONFIGURED — we
    intentionally do not surface a different code so callers cannot
    use the smoke as a "is this remote address reachable" probe.
  - The probe uses urllib (stdlib only, no requests/httpx) with a
    bounded timeout and only issues a GET to /api/tags. No payload.
  - A pluggable transport is accepted for tests; it must NOT open a
    real socket. The production transport is the bound urllib helper.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from .ollama_local_provider_smoke_record import (
    OLLAMA_LOCAL_PROVIDER_SMOKE_STATUS_TOKENS,
    OllamaLocalProviderSmokeRecord,
)

# Hosts we accept as local. Anything else is treated as network.
_LOCAL_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
    }
)


@dataclass(frozen=True)
class _ProbeResult:
    status_code: int
    ok: bool
    timed_out: bool
    error: str = ""


# Transport signature: receives (endpoint, timeout_seconds) and returns ProbeResult.
ProbeTransport = Callable[[str, float], _ProbeResult]


def _real_transport(endpoint: str, timeout_seconds: float) -> _ProbeResult:
    """Stdlib-only localhost probe. NEVER imported by tests."""
    # Lazy import inside the function so this module is safe to load
    # without paying the urllib cost when tests use a mock transport.
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            url=endpoint.rstrip("/") + "/api/tags",
            method="GET",
            headers={"User-Agent": "determinex-ollama-smoke/1"},
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return _ProbeResult(
                status_code=resp.status,
                ok=(200 <= resp.status < 300),
                timed_out=False,
            )
    except TimeoutError:
        return _ProbeResult(status_code=0, ok=False, timed_out=True, error="socket timeout")
    except urllib.error.URLError as exc:
        if "timed out" in str(exc).lower():
            return _ProbeResult(status_code=0, ok=False, timed_out=True, error=str(exc))
        return _ProbeResult(status_code=0, ok=False, timed_out=False, error=str(exc))
    except OSError as exc:
        return _ProbeResult(status_code=0, ok=False, timed_out=False, error=str(exc))


def _host_is_local(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    return host in _LOCAL_HOSTS


def smoke(
    *,
    endpoint: str = "",
    timeout_seconds: float = 1.5,
    transport: ProbeTransport | None = None,
) -> OllamaLocalProviderSmokeRecord:
    """Run the bounded smoke.

    Defaults to BLOCKED_NOT_CONFIGURED so callers must explicitly opt
    in to a localhost probe.
    """
    if not endpoint:
        return OllamaLocalProviderSmokeRecord(
            decision="OLLAMA_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
            endpoint="",
            elapsed_ms=0,
            output_trusted=False,
            network_provider_admitted=False,
            statuses_seen=(
                "OLLAMA_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
                "OLLAMA_PROVIDER_OUTPUT_UNTRUSTED",
            ),
            notes=("endpoint not configured",),
        )

    if not _host_is_local(endpoint):
        # Network endpoint — we refuse to probe.
        return OllamaLocalProviderSmokeRecord(
            decision="OLLAMA_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
            endpoint=endpoint,
            elapsed_ms=0,
            output_trusted=False,
            network_provider_admitted=False,
            statuses_seen=(
                "OLLAMA_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
                "OLLAMA_PROVIDER_OUTPUT_UNTRUSTED",
            ),
            notes=("endpoint host not in local set (127.0.0.1/localhost/::1)",),
        )

    use_transport: ProbeTransport = transport or _real_transport

    start = time.monotonic()
    result = use_transport(endpoint, timeout_seconds)
    elapsed = int((time.monotonic() - start) * 1000)

    if result.timed_out:
        decision = "OLLAMA_PROVIDER_SMOKE_BLOCKED_TIMEOUT"
        return OllamaLocalProviderSmokeRecord(
            decision=decision,
            endpoint=endpoint,
            elapsed_ms=elapsed,
            output_trusted=False,
            network_provider_admitted=False,
            statuses_seen=(decision, "OLLAMA_PROVIDER_OUTPUT_UNTRUSTED"),
            notes=(result.error or "timed out",),
        )

    if not result.ok:
        decision = "OLLAMA_PROVIDER_SMOKE_BLOCKED_UNAVAILABLE"
        return OllamaLocalProviderSmokeRecord(
            decision=decision,
            endpoint=endpoint,
            elapsed_ms=elapsed,
            output_trusted=False,
            network_provider_admitted=False,
            statuses_seen=(decision, "OLLAMA_PROVIDER_OUTPUT_UNTRUSTED"),
            notes=(result.error or f"status {result.status_code}",),
        )

    decision = "OLLAMA_PROVIDER_SMOKE_PASSED"
    return OllamaLocalProviderSmokeRecord(
        decision=decision,
        endpoint=endpoint,
        elapsed_ms=elapsed,
        output_trusted=False,
        network_provider_admitted=False,
        statuses_seen=(decision, "OLLAMA_PROVIDER_OUTPUT_UNTRUSTED"),
        notes=("localhost probe ok; output remains untrusted",),
    )


__all__ = [
    "smoke",
    "OLLAMA_LOCAL_PROVIDER_SMOKE_STATUS_TOKENS",
    "OllamaLocalProviderSmokeRecord",
]
