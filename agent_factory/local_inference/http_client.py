from __future__ import annotations

import httpx

from agent_factory.local_inference.config import LocalInferenceEndpoint


def create_private_http_client(endpoint: LocalInferenceEndpoint) -> httpx.Client:
    return httpx.Client(timeout=endpoint.timeout_seconds, trust_env=False)


def create_private_async_http_client(endpoint: LocalInferenceEndpoint) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=endpoint.timeout_seconds, trust_env=False)
