from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Protocol, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener


DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_MAX_TIMEOUT_SECONDS = 30.0
_SCHEMA_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class MCPTransportError(RuntimeError):
    """A deliberately low-detail error safe to show outside the transport."""


JSONScalar: TypeAlias = str | int | float | bool | None
FrozenJSON: TypeAlias = JSONScalar | tuple["FrozenJSON", ...] | Mapping[str, "FrozenJSON"]
RawMCPResponse: TypeAlias = bytes | str | Mapping[str, object]


def _freeze_json(value: object) -> FrozenJSON:
    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJSON] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise MCPTransportError("MCP response payload is invalid")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            raise MCPTransportError("MCP response payload is invalid")
        return value
    raise MCPTransportError("MCP response payload is invalid")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise MCPTransportError("MCP JSON value is invalid") from error


def _schema_digest(schema: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(schema)).hexdigest()


def _validate_tool_name(tool_name: str) -> None:
    if not isinstance(tool_name, str) or _TOOL_NAME.fullmatch(tool_name) is None:
        raise MCPTransportError("MCP tool name is invalid")


def _validate_timeout(timeout_seconds: float, maximum: float) -> float:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or timeout_seconds <= 0
        or timeout_seconds > maximum
    ):
        raise MCPTransportError("MCP timeout is outside the allowed range")
    return float(timeout_seconds)


@dataclass(frozen=True, slots=True)
class MCPResult:
    tool_name: str
    schema_digest: str
    payload: Mapping[str, FrozenJSON]

    def __post_init__(self) -> None:
        _validate_tool_name(self.tool_name)
        if _SCHEMA_DIGEST.fullmatch(self.schema_digest) is None:
            raise MCPTransportError("MCP schema digest is invalid")
        frozen = _freeze_json(self.payload)
        if not isinstance(frozen, Mapping):
            raise MCPTransportError("MCP response payload is invalid")
        object.__setattr__(self, "payload", frozen)


class MCPTransport(Protocol):
    def call(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> MCPResult: ...


MCPInvoker: TypeAlias = Callable[[str, Mapping[str, object], float], RawMCPResponse]
HTTPOpener: TypeAlias = Callable[[Request, float], object]


class BoundedMCPTransport:
    """Validates an injected MCP caller without coupling providers to a client SDK."""

    def __init__(
        self,
        invoker: MCPInvoker,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_timeout_seconds: float = DEFAULT_MAX_TIMEOUT_SECONDS,
    ) -> None:
        if not callable(invoker):
            raise TypeError("invoker must be callable")
        if isinstance(max_response_bytes, bool) or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        if (
            isinstance(max_timeout_seconds, bool)
            or not math.isfinite(float(max_timeout_seconds))
            or max_timeout_seconds <= 0
        ):
            raise ValueError("max_timeout_seconds must be positive and finite")
        self._invoker = invoker
        self._max_response_bytes = int(max_response_bytes)
        self._max_timeout_seconds = float(max_timeout_seconds)

    def call(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> MCPResult:
        _validate_tool_name(tool_name)
        timeout = _validate_timeout(timeout_seconds, self._max_timeout_seconds)
        if not isinstance(arguments, Mapping):
            raise MCPTransportError("MCP arguments are invalid")
        arguments_bytes = _canonical_json_bytes(arguments)
        safe_arguments = json.loads(arguments_bytes.decode("utf-8"))
        if not isinstance(safe_arguments, dict):
            raise MCPTransportError("MCP arguments are invalid")

        try:
            raw = self._invoker(tool_name, MappingProxyType(safe_arguments), timeout)
        except TimeoutError as error:
            raise MCPTransportError("MCP call timed out") from error
        except MCPTransportError:
            raise
        except Exception as error:
            # Raw exception messages can contain tokens, URLs, or remote response bodies.
            raise MCPTransportError("MCP call failed") from error

        return self._decode(raw)

    def _decode(self, raw: RawMCPResponse) -> MCPResult:
        if isinstance(raw, bytes):
            encoded = raw
        elif isinstance(raw, str):
            encoded = raw.encode("utf-8")
        elif isinstance(raw, Mapping):
            encoded = _canonical_json_bytes(raw)
        else:
            raise MCPTransportError("MCP response type is invalid")

        if len(encoded) > self._max_response_bytes:
            raise MCPTransportError("MCP response exceeded the size limit")
        try:
            decoded = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MCPTransportError("MCP response is not valid UTF-8 JSON") from error
        if not isinstance(decoded, dict):
            raise MCPTransportError("MCP response envelope is invalid")
        if "error" in decoded:
            raise MCPTransportError("MCP remote tool returned an error")
        if set(decoded) != {"tool_name", "schema_digest", "payload"}:
            raise MCPTransportError("MCP response envelope is invalid")
        if not isinstance(decoded["payload"], dict):
            raise MCPTransportError("MCP response payload is invalid")
        try:
            return MCPResult(
                tool_name=decoded["tool_name"],
                schema_digest=decoded["schema_digest"],
                payload=decoded["payload"],
            )
        except (TypeError, MCPTransportError) as error:
            raise MCPTransportError("MCP response envelope is invalid") from error


class HttpMCPTransport:
    """通过无代理、无 URL 凭据的本地 JSON 桥接调用真实 MCP 服务。"""

    def __init__(
        self,
        endpoint: str,
        *,
        opener: HTTPOpener | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_timeout_seconds: float = DEFAULT_MAX_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(endpoint, str) or any(
            character.isspace() or ord(character) < 32
            for character in endpoint
        ):
            raise ValueError("MCP endpoint is invalid")
        try:
            parts = urlsplit(endpoint)
            _ = parts.port
        except ValueError:
            raise ValueError("MCP endpoint is invalid") from None
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or parts.path != "/invoke"
        ):
            raise ValueError("MCP endpoint is invalid")
        if isinstance(max_response_bytes, bool) or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self._endpoint = endpoint
        self._max_response_bytes = int(max_response_bytes)
        self._opener = opener or self._default_opener()
        self._bounded = BoundedMCPTransport(
            self._invoke,
            max_response_bytes=max_response_bytes,
            max_timeout_seconds=max_timeout_seconds,
        )

    @staticmethod
    def _default_opener() -> HTTPOpener:
        director: OpenerDirector = build_opener(ProxyHandler({}))

        def open_request(request: Request, timeout: float) -> object:
            return director.open(request, timeout=timeout)

        return open_request

    def _invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> bytes:
        body = _canonical_json_bytes(
            {"tool_name": tool_name, "arguments": dict(arguments)}
        )
        request = Request(
            self._endpoint,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            response = self._opener(request, timeout_seconds)
            with response:  # type: ignore[union-attr]
                length = getattr(response, "headers", {}).get(
                    "Content-Length"
                )
                if length is not None and int(length) > self._max_response_bytes:
                    raise MCPTransportError(
                        "MCP response exceeded the size limit"
                    )
                payload = response.read(self._max_response_bytes + 1)  # type: ignore[union-attr]
        except MCPTransportError:
            raise
        except (HTTPError, URLError, OSError, TypeError, ValueError):
            raise MCPTransportError("MCP HTTP call failed") from None
        if not isinstance(payload, bytes):
            raise MCPTransportError("MCP HTTP response is invalid")
        if len(payload) > self._max_response_bytes:
            raise MCPTransportError("MCP response exceeded the size limit")
        return payload

    def call(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> MCPResult:
        return self._bounded.call(tool_name, arguments, timeout_seconds)


@dataclass(frozen=True, slots=True)
class _RecordedCall:
    arguments_json: bytes
    result: MCPResult


class RecordedMCPTransport:
    """Offline-only transport backed by explicit, versioned synthetic fixtures."""

    def __init__(
        self,
        fixtures: Iterable[Mapping[str, object]],
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_timeout_seconds: float = DEFAULT_MAX_TIMEOUT_SECONDS,
    ) -> None:
        if isinstance(max_response_bytes, bool) or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        if (
            isinstance(max_timeout_seconds, bool)
            or not math.isfinite(float(max_timeout_seconds))
            or max_timeout_seconds <= 0
        ):
            raise ValueError("max_timeout_seconds must be positive and finite")
        self._max_response_bytes = int(max_response_bytes)
        self._max_timeout_seconds = float(max_timeout_seconds)
        calls: dict[str, _RecordedCall] = {}
        for fixture in fixtures:
            tool_name, call = self._parse_fixture(fixture)
            if tool_name in calls:
                raise MCPTransportError("duplicate recorded MCP tool")
            calls[tool_name] = call
        if not calls:
            raise MCPTransportError("no recorded MCP fixtures were provided")
        self._calls = MappingProxyType(calls)

    @classmethod
    def from_files(
        cls,
        paths: Iterable[Path],
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_timeout_seconds: float = DEFAULT_MAX_TIMEOUT_SECONDS,
    ) -> RecordedMCPTransport:
        fixtures: list[Mapping[str, object]] = []
        for path in paths:
            try:
                raw = path.read_bytes()
            except OSError as error:
                raise MCPTransportError("recorded MCP fixture is unavailable") from error
            if len(raw) > max_response_bytes:
                raise MCPTransportError("recorded MCP fixture exceeded the size limit")
            try:
                fixture = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise MCPTransportError("recorded MCP fixture is invalid") from error
            if not isinstance(fixture, dict):
                raise MCPTransportError("recorded MCP fixture is invalid")
            fixtures.append(fixture)
        return cls(
            fixtures,
            max_response_bytes=max_response_bytes,
            max_timeout_seconds=max_timeout_seconds,
        )

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_timeout_seconds: float = DEFAULT_MAX_TIMEOUT_SECONDS,
    ) -> RecordedMCPTransport:
        if not directory.is_dir():
            raise MCPTransportError("recorded MCP fixture directory is unavailable")
        return cls.from_files(
            sorted(directory.glob("*.json")),
            max_response_bytes=max_response_bytes,
            max_timeout_seconds=max_timeout_seconds,
        )

    def call(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> MCPResult:
        _validate_tool_name(tool_name)
        _validate_timeout(timeout_seconds, self._max_timeout_seconds)
        if not isinstance(arguments, Mapping):
            raise MCPTransportError("MCP arguments are invalid")
        recorded = self._calls.get(tool_name)
        if recorded is None:
            raise MCPTransportError("MCP tool has no recorded fixture")
        if _canonical_json_bytes(arguments) != recorded.arguments_json:
            raise MCPTransportError("MCP arguments do not match the recorded fixture")
        return recorded.result

    def _parse_fixture(
        self,
        fixture: Mapping[str, object],
    ) -> tuple[str, _RecordedCall]:
        if fixture.get("fixture_version") != 1 or fixture.get("synthetic") is not True:
            raise MCPTransportError("recorded MCP fixture version is unsupported")
        tool = fixture.get("tool")
        arguments = fixture.get("arguments")
        payload = fixture.get("result")
        if not isinstance(tool, Mapping) or not isinstance(arguments, Mapping):
            raise MCPTransportError("recorded MCP fixture is invalid")
        if not isinstance(payload, Mapping):
            raise MCPTransportError("recorded MCP fixture is invalid")
        tool_name = tool.get("name")
        schema_digest = tool.get("schema_digest")
        input_schema = tool.get("input_schema")
        if not isinstance(tool_name, str) or not isinstance(schema_digest, str):
            raise MCPTransportError("recorded MCP fixture tool contract is invalid")
        _validate_tool_name(tool_name)
        if _SCHEMA_DIGEST.fullmatch(schema_digest) is None:
            raise MCPTransportError("recorded MCP fixture schema digest is invalid")
        if _schema_digest(input_schema) != schema_digest:
            raise MCPTransportError("recorded MCP fixture schema digest does not match")
        response_size = len(
            _canonical_json_bytes(
                {
                    "tool_name": tool_name,
                    "schema_digest": schema_digest,
                    "payload": payload,
                }
            )
        )
        if response_size > self._max_response_bytes:
            raise MCPTransportError("recorded MCP response exceeded the size limit")
        return tool_name, _RecordedCall(
            arguments_json=_canonical_json_bytes(arguments),
            result=MCPResult(
                tool_name=tool_name,
                schema_digest=schema_digest,
                payload=payload,
            ),
        )


__all__ = [
    "BoundedMCPTransport",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_MAX_TIMEOUT_SECONDS",
    "HttpMCPTransport",
    "MCPResult",
    "MCPTransport",
    "MCPTransportError",
    "RecordedMCPTransport",
]
