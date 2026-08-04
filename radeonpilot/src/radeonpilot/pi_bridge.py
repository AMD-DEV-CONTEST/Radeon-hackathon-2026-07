"""HTTP client for the local Pi bridge multi-agent service."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class PiBridgeError(RuntimeError):
    pass


class PiBridgeClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (
            base_url or os.environ.get("PI_BRIDGE_URL") or "http://127.0.0.1:8787"
        ).rstrip("/")
        self.timeout = timeout
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise PiBridgeError("PiBridge URL must use HTTP(S) on a loopback host")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def run_agents(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/orchestrate", payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PiBridgeError(f"PiBridge HTTP {exc.code} for {path}: {detail}") from exc
        except URLError as exc:
            raise PiBridgeError(f"PiBridge connection failed for {path}: {exc.reason}") from exc
        except OSError as exc:
            raise PiBridgeError(f"PiBridge request failed for {path}: {exc}") from exc
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise PiBridgeError(f"PiBridge returned non-JSON response for {path}") from exc
        if not isinstance(parsed, dict):
            raise PiBridgeError(f"PiBridge returned a non-object JSON response for {path}")
        return parsed
