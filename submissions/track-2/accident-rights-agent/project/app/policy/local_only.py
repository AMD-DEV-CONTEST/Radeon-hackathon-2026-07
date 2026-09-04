"""Fail-closed validation for the local vLLM endpoint."""

from __future__ import annotations

import os
from urllib.parse import SplitResult, urlsplit, urlunsplit

DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
ALLOWED_PORT = 8000
ALLOWED_PATHS = frozenset({"", "/", "/v1", "/v1/"})


class LocalEndpointError(ValueError):
    """Raised when a model endpoint could leave the local instance."""


def require_local_vllm_base_url(value: str | None = None) -> str:
    """Return a canonical local vLLM URL or raise ``LocalEndpointError``."""

    candidate = (value or os.getenv("VLLM_BASE_URL") or DEFAULT_BASE_URL).strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise LocalEndpointError(f"Invalid VLLM_BASE_URL: {exc}") from exc

    if parsed.scheme != "http":
        raise LocalEndpointError("VLLM_BASE_URL must use plain HTTP on loopback.")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise LocalEndpointError(
            "Remote model endpoints are forbidden; use 127.0.0.1, localhost, or ::1."
        )
    if port != ALLOWED_PORT:
        raise LocalEndpointError(f"vLLM must use local port {ALLOWED_PORT}.")
    if parsed.username or parsed.password:
        raise LocalEndpointError("Credentials must not be embedded in VLLM_BASE_URL.")
    if parsed.query or parsed.fragment:
        raise LocalEndpointError("Query strings and fragments are not allowed.")
    if parsed.path not in ALLOWED_PATHS:
        raise LocalEndpointError("VLLM_BASE_URL path must be /v1.")

    host = parsed.hostname
    assert host is not None
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    canonical = SplitResult("http", netloc, "/v1", "", "")
    return urlunsplit(canonical)


def local_api_url(path: str, base_url: str | None = None) -> str:
    """Build a URL below the validated local OpenAI-compatible `/v1` root."""

    if not path.startswith("/"):
        path = f"/{path}"
    if ".." in path:
        raise LocalEndpointError("API paths may not contain parent traversal.")
    return f"{require_local_vllm_base_url(base_url)}{path}"
