"""Real Ollama provider detection.

Two-step localhost-only probe:
  1. Check that the `ollama` CLI binary is on PATH (or a caller-supplied
     binary_locator says so). If not → BLOCKED_NOT_INSTALLED.
  2. GET <endpoint>/api/tags with a strict timeout. Capture the model
     names list when the daemon answers. Map errors to:
       not running → BLOCKED_NOT_RUNNING
       timeout     → BLOCKED_TIMEOUT
       non-local   → BLOCKED_NETWORK_PROVIDER

No live inference. No source/repo input. No patch generation.
Detection is a pure read; it never spawns Ollama or pulls a model.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from .real_ollama_provider_detection_record import (
    REAL_OLLAMA_PROVIDER_DETECTION_STATUS_TOKENS,
    RealOllamaProviderDetectionRecord,
)

_LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class _TagsResult:
    """Result of a GET /api/tags probe."""

    ok: bool
    timed_out: bool
    not_running: bool
    models: tuple[str, ...] = ()
    error: str = ""


TagsTransport = Callable[[str, float], _TagsResult]
BinaryLocator = Callable[[], str | None]


def _default_binary_locator() -> str | None:
    return shutil.which("ollama")


def _default_tags_transport(endpoint: str, timeout_seconds: float) -> _TagsResult:
    """Stdlib urllib probe — never imported by tests."""
    import json as _json
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            url=endpoint.rstrip("/") + "/api/tags",
            method="GET",
            headers={"User-Agent": "determinex-ollama-detect/1"},
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            if not (200 <= resp.status < 300):
                return _TagsResult(
                    ok=False,
                    timed_out=False,
                    not_running=False,
                    error=f"status {resp.status}",
                )
            try:
                payload = _json.loads(resp.read().decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError) as exc:
                return _TagsResult(
                    ok=False,
                    timed_out=False,
                    not_running=False,
                    error=f"malformed json: {exc}",
                )
            raw = payload.get("models") if isinstance(payload, dict) else None
            names: list[str] = []
            if isinstance(raw, list):
                for m in raw:
                    if isinstance(m, dict):
                        nm = m.get("name")
                        if isinstance(nm, str) and nm:
                            names.append(nm)
            return _TagsResult(
                ok=True,
                timed_out=False,
                not_running=False,
                models=tuple(names),
            )
    except TimeoutError:
        return _TagsResult(
            ok=False,
            timed_out=True,
            not_running=False,
            error="socket timeout",
        )
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc)).lower()
        if "timed out" in reason:
            return _TagsResult(
                ok=False,
                timed_out=True,
                not_running=False,
                error=str(exc),
            )
        # Connection refused → not running.
        if "refused" in reason or "actively refused" in reason:
            return _TagsResult(
                ok=False,
                timed_out=False,
                not_running=True,
                error=str(exc),
            )
        return _TagsResult(
            ok=False,
            timed_out=False,
            not_running=False,
            error=str(exc),
        )
    except OSError as exc:
        return _TagsResult(
            ok=False,
            timed_out=False,
            not_running=False,
            error=str(exc),
        )


def _host_is_local(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    return host in _LOCAL_HOSTS


def detect(
    *,
    endpoint: str = "http://127.0.0.1:11434",
    timeout_seconds: float = 1.5,
    binary_locator: BinaryLocator | None = None,
    tags_transport: TagsTransport | None = None,
) -> RealOllamaProviderDetectionRecord:
    """Detect a real local Ollama provider. Read-only.

    Default endpoint is the canonical localhost daemon address.
    Callers must pass a localhost endpoint; non-local hosts are
    refused as a network provider attempt.
    """
    if not _host_is_local(endpoint):
        return RealOllamaProviderDetectionRecord(
            decision="REAL_OLLAMA_PROVIDER_BLOCKED_NETWORK_PROVIDER",
            endpoint=endpoint,
            elapsed_ms=0,
            network_provider_admitted=False,
            live_inference_called=False,
            notes=("endpoint host not in local set (127.0.0.1/localhost/::1)",),
        )

    locate = binary_locator or _default_binary_locator
    bin_path = locate()
    if not bin_path:
        return RealOllamaProviderDetectionRecord(
            decision="REAL_OLLAMA_PROVIDER_BLOCKED_NOT_INSTALLED",
            endpoint=endpoint,
            elapsed_ms=0,
            network_provider_admitted=False,
            live_inference_called=False,
            notes=("ollama binary not found on PATH",),
        )

    probe = tags_transport or _default_tags_transport
    start = time.monotonic()
    result = probe(endpoint, timeout_seconds)
    elapsed = int((time.monotonic() - start) * 1000)

    if result.timed_out:
        return RealOllamaProviderDetectionRecord(
            decision="REAL_OLLAMA_PROVIDER_BLOCKED_TIMEOUT",
            endpoint=endpoint,
            elapsed_ms=elapsed,
            network_provider_admitted=False,
            live_inference_called=False,
            notes=(result.error or "timed out",),
        )

    if result.not_running:
        return RealOllamaProviderDetectionRecord(
            decision="REAL_OLLAMA_PROVIDER_BLOCKED_NOT_RUNNING",
            endpoint=endpoint,
            elapsed_ms=elapsed,
            network_provider_admitted=False,
            live_inference_called=False,
            notes=(result.error or "daemon not running",),
        )

    if not result.ok:
        return RealOllamaProviderDetectionRecord(
            decision="REAL_OLLAMA_PROVIDER_BLOCKED_NOT_RUNNING",
            endpoint=endpoint,
            elapsed_ms=elapsed,
            network_provider_admitted=False,
            live_inference_called=False,
            notes=(result.error or "daemon responded unhealthily",),
        )

    return RealOllamaProviderDetectionRecord(
        decision="REAL_OLLAMA_PROVIDER_DETECTED",
        endpoint=endpoint,
        elapsed_ms=elapsed,
        models=result.models,
        network_provider_admitted=False,
        live_inference_called=False,
        notes=(
            f"ollama binary at {bin_path}",
            f"daemon responded with {len(result.models)} model(s)",
            "read-only probe; no live inference performed",
        ),
    )


__all__ = [
    "detect",
    "REAL_OLLAMA_PROVIDER_DETECTION_STATUS_TOKENS",
    "RealOllamaProviderDetectionRecord",
]
