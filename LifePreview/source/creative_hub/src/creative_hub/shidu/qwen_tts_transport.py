from __future__ import annotations

import json
import math
from collections.abc import Mapping
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener
from uuid import uuid4


class QwenTTSMCPTransportError(RuntimeError):
    """Fail-closed error that never includes a remote response body."""


class StreamableHttpQwenTTSMCPTransport:
    """Small stateless Streamable HTTP MCP client for the local Qwen service."""

    _DISCOVERY_TOOL = "qwen_tts.phase2_discover"

    def __init__(
        self,
        endpoint: str,
        *,
        opener: OpenerDirector | None = None,
        max_response_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        try:
            parts = urlsplit(endpoint)
            _ = parts.port
        except (TypeError, ValueError):
            raise ValueError("Qwen TTS MCP endpoint is invalid") from None
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or parts.path != "/mcp"
        ):
            raise ValueError("Qwen TTS MCP endpoint is invalid")
        if isinstance(max_response_bytes, bool) or max_response_bytes < 1:
            raise ValueError("Qwen TTS MCP response limit is invalid")
        self._endpoint = endpoint
        self._opener = opener or build_opener(ProxyHandler({}))
        self._max_response_bytes = int(max_response_bytes)
        self._lock = Lock()

    def discover(self) -> Mapping[str, object]:
        return self._call_tool(self._DISCOVERY_TOOL, {}, timeout_seconds=10.0)

    def call_custom_voice(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        idempotency_key: str,
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        if tool_name != "qwen_tts.custom_voice":
            raise QwenTTSMCPTransportError("Qwen TTS MCP tool contract mismatch")
        payload = dict(arguments)
        payload["idempotency_key"] = idempotency_key
        return self._call_tool(
            tool_name,
            payload,
            timeout_seconds=timeout_seconds,
        )

    def _call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 600
        ):
            raise QwenTTSMCPTransportError("Qwen TTS MCP timeout is invalid")
        request_id = uuid4().hex
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": dict(arguments),
                },
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self._endpoint,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._lock:
                response = self._opener.open(
                    request,
                    timeout=float(timeout_seconds),
                )
                with response:
                    raw = response.read(self._max_response_bytes + 1)
        except TimeoutError:
            raise
        except (HTTPError, URLError, OSError, TypeError, ValueError):
            raise ConnectionError("Qwen TTS MCP service is unavailable") from None
        if not isinstance(raw, bytes) or len(raw) > self._max_response_bytes:
            raise QwenTTSMCPTransportError("Qwen TTS MCP response is invalid")
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise QwenTTSMCPTransportError("Qwen TTS MCP response is invalid") from None
        if (
            not isinstance(envelope, dict)
            or envelope.get("jsonrpc") != "2.0"
            or envelope.get("id") != request_id
            or "error" in envelope
            or not isinstance(envelope.get("result"), dict)
        ):
            raise QwenTTSMCPTransportError("Qwen TTS MCP response is invalid")
        result = envelope["result"]
        structured = result.get("structuredContent")
        if result.get("isError") is True or not isinstance(structured, dict):
            raise QwenTTSMCPTransportError("Qwen TTS MCP tool failed")
        return structured


__all__ = [
    "QwenTTSMCPTransportError",
    "StreamableHttpQwenTTSMCPTransport",
]
