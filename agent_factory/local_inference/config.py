from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from typing import Literal, cast
from urllib.parse import urlparse


LOCAL_INFERENCE_ENDPOINT_ENV = "AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT"
LOCAL_INFERENCE_ALLOWED_HOSTS_ENV = "AGENTFACTORY_LOCAL_INFERENCE_ALLOWED_HOSTS"
LOCAL_EMBEDDING_ENDPOINT_ENV = "AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT"
LOCAL_EMBEDDING_ALLOWED_HOSTS_ENV = "AGENTFACTORY_LOCAL_EMBEDDING_ALLOWED_HOSTS"
LOCAL_IMAGE_ENDPOINT_ENV = "AGENTFACTORY_LOCAL_IMAGE_ENDPOINT"
LOCAL_IMAGE_ALLOWED_HOSTS_ENV = "AGENTFACTORY_LOCAL_IMAGE_ALLOWED_HOSTS"
INFERENCE_RUNTIME_MODE_ENV = "AGENTFACTORY_INFERENCE_RUNTIME_MODE"
INFERENCE_TELEMETRY_ENDPOINT_ENV = "AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT"
DEFAULT_LOCAL_INFERENCE_ENDPOINT = "http://127.0.0.1:8003/v1"
DEFAULT_LOCAL_EMBEDDING_ENDPOINT = "http://127.0.0.1:8002"
DEFAULT_LOCAL_IMAGE_ENDPOINT = "http://127.0.0.1:8005/v1"
DEFAULT_INFERENCE_TELEMETRY_ENDPOINT = "http://127.0.0.1:8004"
InferenceRuntimeMode = Literal["managed", "external"]


@dataclass(frozen=True, slots=True)
class LocalInferenceEndpoint:
    base_url: str
    timeout_seconds: float

    def endpoint(self, path: str) -> str:
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url.rstrip('/')}{suffix}"

    def server_endpoint(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}"


def load_local_inference_endpoint(*, timeout_seconds: float | None = None) -> LocalInferenceEndpoint:
    return load_local_endpoint(
        endpoint_env=LOCAL_INFERENCE_ENDPOINT_ENV,
        default_endpoint=DEFAULT_LOCAL_INFERENCE_ENDPOINT,
        allowed_hosts_env=LOCAL_INFERENCE_ALLOWED_HOSTS_ENV,
        timeout_env="AGENTFACTORY_LOCAL_INFERENCE_TIMEOUT_SECONDS",
        timeout_seconds=timeout_seconds,
    )


def load_local_embedding_endpoint(*, timeout_seconds: float | None = None) -> LocalInferenceEndpoint:
    return load_local_endpoint(
        endpoint_env=LOCAL_EMBEDDING_ENDPOINT_ENV,
        default_endpoint=DEFAULT_LOCAL_EMBEDDING_ENDPOINT,
        allowed_hosts_env=LOCAL_EMBEDDING_ALLOWED_HOSTS_ENV,
        timeout_env="AGENTFACTORY_LOCAL_EMBEDDING_TIMEOUT_SECONDS",
        timeout_seconds=timeout_seconds,
    )


def load_local_image_endpoint(*, timeout_seconds: float | None = None) -> LocalInferenceEndpoint:
    return load_local_endpoint(
        endpoint_env=LOCAL_IMAGE_ENDPOINT_ENV,
        default_endpoint=DEFAULT_LOCAL_IMAGE_ENDPOINT,
        allowed_hosts_env=LOCAL_IMAGE_ALLOWED_HOSTS_ENV,
        timeout_env="AGENTFACTORY_LOCAL_IMAGE_TIMEOUT_SECONDS",
        timeout_seconds=timeout_seconds,
    )


def load_inference_telemetry_endpoint(*, timeout_seconds: float | None = None) -> LocalInferenceEndpoint:
    return load_local_endpoint(
        endpoint_env=INFERENCE_TELEMETRY_ENDPOINT_ENV,
        default_endpoint=DEFAULT_INFERENCE_TELEMETRY_ENDPOINT,
        allowed_hosts_env=LOCAL_INFERENCE_ALLOWED_HOSTS_ENV,
        timeout_env="AGENTFACTORY_LOCAL_INFERENCE_TIMEOUT_SECONDS",
        timeout_seconds=timeout_seconds,
    )


def load_inference_runtime_mode() -> InferenceRuntimeMode:
    value = str(os.getenv(INFERENCE_RUNTIME_MODE_ENV) or "managed").strip().lower()
    if value not in {"managed", "external"}:
        raise ValueError(f"{INFERENCE_RUNTIME_MODE_ENV} must be managed or external")
    return cast(InferenceRuntimeMode, value)


def load_local_endpoint(
    *,
    endpoint_env: str,
    default_endpoint: str,
    allowed_hosts_env: str,
    timeout_env: str,
    timeout_seconds: float | None = None,
) -> LocalInferenceEndpoint:
    raw_url = str(os.getenv(endpoint_env) or default_endpoint).strip()
    parsed = urlparse(raw_url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("local inference endpoint must be an http URL with a hostname")
    _assert_local_host(parsed.hostname, allowed_hosts_env=allowed_hosts_env)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("local inference endpoint must not contain credentials, query, or fragment")
    effective_timeout = timeout_seconds if timeout_seconds is not None else _timeout_from_env(timeout_env)
    return LocalInferenceEndpoint(base_url=raw_url.rstrip("/"), timeout_seconds=effective_timeout)


def _assert_local_host(hostname: str, *, allowed_hosts_env: str) -> None:
    normalized = hostname.strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        address = None
    if address is not None and (address.is_loopback or address.is_private or address.is_link_local):
        return
    allowed_hosts = {
        item.strip().lower()
        for item in str(os.getenv(allowed_hosts_env) or "").split(",")
        if item.strip()
    }
    if normalized not in allowed_hosts:
        raise ValueError(
            f"local inference host {hostname!r} is not loopback/private and is not listed in "
            f"{allowed_hosts_env}"
        )


def _timeout_from_env(timeout_env: str) -> float:
    raw = str(os.getenv(timeout_env) or "").strip()
    if not raw:
        return 600.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("local inference timeout must be a number") from exc
    if value <= 0:
        raise ValueError("local inference timeout must be greater than zero")
    return value
