"""Authenticated loopback proxy for an OpenAI-compatible local vLLM backend.

The proxy is intentionally self-contained so it can run in a target runtime
without importing desktop services.  Its listener is always ``127.0.0.1`` and
its backend must be a literal loopback ``http`` URL.  Authentication is loaded
once, at startup, from the protected file named by
``XENIX_RUNTIME_BEARER_TOKEN_FILE``; no command-line token is accepted.
"""

from __future__ import annotations

import argparse
import hmac
import http.client
import ipaddress
import json
import math
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit


_TOKEN_FILE_ENVIRONMENT_NAME: Final = "XENIX_RUNTIME_BEARER_TOKEN_FILE"
_TOKEN_PATTERN: Final = re.compile(rb"[A-Za-z0-9_-]{24,512}\Z")
_HEADER_NAME_PATTERN: Final = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_MAX_TOKEN_BYTES: Final = 512
_TOKEN_FILE_MODE: Final = 0o600
_STREAM_CHUNK_BYTES: Final = 16 * 1024
_DEFAULT_BACKEND_TIMEOUT_SECONDS: Final = 300.0
_MAX_BACKEND_TIMEOUT_SECONDS: Final = 86_400.0
_DEFAULT_BACKEND_STARTUP_TIMEOUT_SECONDS: Final = 300.0
_MAX_BACKEND_STARTUP_TIMEOUT_SECONDS: Final = 1_800.0
_BACKEND_CONNECT_RETRY_SECONDS: Final = 0.1
_BACKEND_STOP_TIMEOUT_SECONDS: Final = 15.0
_BACKEND_SUPERVISION_POLL_SECONDS: Final = 0.2
_BODY_METHODS: Final = frozenset({"POST", "PUT", "PATCH"})
_SENSITIVE_BACKEND_OPTION: Final = re.compile(
    r"(?:api[-_]?key|authorization|bearer|credential|password|private[-_]?key|secret|token|hf[-_]?token)\Z",
    re.IGNORECASE,
)
_HOP_BY_HOP_HEADERS: Final = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


class _StartupError(Exception):
    """Startup could not safely obtain the required non-command-line secret."""


class _ClientRequestError(Exception):
    """A client request cannot be safely forwarded to the local backend."""

    def __init__(self, status: HTTPStatus) -> None:
        self.status = status


class _BackendProtocolError(Exception):
    """The local backend returned a response this HTTP proxy cannot relay."""


class _BackendCommandError(Exception):
    """The supplied vLLM child command cannot satisfy the loopback contract."""


class _BackendStartupError(Exception):
    """The supervised backend failed before the proxy could safely serve."""


@dataclass(frozen=True, slots=True)
class _LoopbackBackend:
    """A validated non-secret loopback destination for the local model server."""

    host: str
    port: int
    host_header: str


@dataclass(frozen=True, slots=True)
class _BackendCommand:
    """One redacted child command that must remain in the proxy process group."""

    arguments: tuple[str, ...] = field(repr=False)

    def __repr__(self) -> str:
        return "_BackendCommand(<redacted>)"


@dataclass(frozen=True, slots=True)
class _ProxyArguments:
    """Validated non-secret launch arguments for this standalone target process."""

    listen_port: int
    backend: _LoopbackBackend
    backend_command: _BackendCommand | None = field(repr=False)
    backend_timeout_seconds: float
    backend_startup_timeout_seconds: float


def _parse_port(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise argparse.ArgumentTypeError("port must be an integer")
    port = int(value)
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _parse_timeout(value: str) -> float:
    return _parse_bounded_seconds(
        value,
        label="backend timeout",
        maximum=_MAX_BACKEND_TIMEOUT_SECONDS,
    )


def _parse_backend_startup_timeout(value: str) -> float:
    return _parse_bounded_seconds(
        value,
        label="backend startup timeout",
        maximum=_MAX_BACKEND_STARTUP_TIMEOUT_SECONDS,
    )


def _parse_bounded_seconds(value: str, *, label: str, maximum: float) -> float:
    try:
        timeout = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{label} must be a number") from None
    if not math.isfinite(timeout) or not 0 < timeout <= maximum:
        raise argparse.ArgumentTypeError(f"{label} is outside the supported bound")
    return timeout


def _literal_loopback_host(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "%" in value:
        raise ValueError
    address = ipaddress.ip_address(value)
    if not address.is_loopback:
        raise ValueError
    return str(address)


def _make_loopback_backend(host: str, port: int) -> _LoopbackBackend:
    rendered_host = f"[{host}]" if ":" in host else host
    return _LoopbackBackend(host=host, port=port, host_header=f"{rendered_host}:{port}")


def _parse_backend_url(value: str) -> _LoopbackBackend:
    """Admit only a literal-IP, root-path HTTP backend on this host."""

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise argparse.ArgumentTypeError("backend URL is invalid") from None
    if (
        parsed.scheme != "http"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        raise argparse.ArgumentTypeError("backend URL must be a root-path loopback http URL without credentials")

    try:
        canonical_host = _literal_loopback_host(parsed.hostname)
    except ValueError:
        raise argparse.ArgumentTypeError("backend URL must use a literal loopback IP address") from None
    backend_port = 80 if port is None else port
    if not 1 <= backend_port <= 65_535:
        raise argparse.ArgumentTypeError("backend URL port is invalid")
    return _make_loopback_backend(canonical_host, backend_port)


def _validated_backend_command(values: list[str] | None) -> _BackendCommand | None:
    if values is None:
        return None
    arguments = tuple(values)
    if not arguments or arguments[0].startswith("-"):
        raise _BackendCommandError()
    for argument in arguments:
        if (
            not isinstance(argument, str)
            or not argument
            or len(argument) > 8_192
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in argument)
        ):
            raise _BackendCommandError()
        if argument.startswith("--"):
            option_name = argument[2:].split("=", 1)[0].casefold()
            if _SENSITIVE_BACKEND_OPTION.fullmatch(option_name):
                raise _BackendCommandError()
    return _BackendCommand(arguments)


def _backend_command_option_values(command: _BackendCommand, option: str) -> tuple[str, ...]:
    values: list[str] = []
    index = 0
    while index < len(command.arguments):
        argument = command.arguments[index]
        if argument == option:
            index += 1
            if index >= len(command.arguments):
                raise _BackendCommandError()
            values.append(command.arguments[index])
        elif argument.startswith(f"{option}="):
            values.append(argument[len(option) + 1 :])
        index += 1
    return tuple(values)


def _backend_from_command(command: _BackendCommand) -> _LoopbackBackend:
    hosts = _backend_command_option_values(command, "--host")
    ports = _backend_command_option_values(command, "--port")
    if len(hosts) != 1 or len(ports) != 1:
        raise _BackendCommandError()
    try:
        host = _literal_loopback_host(hosts[0])
        port = _parse_port(ports[0])
    except (ValueError, argparse.ArgumentTypeError):
        raise _BackendCommandError() from None
    return _make_loopback_backend(host, port)


def _resolve_backend(
    configured_backend: _LoopbackBackend | None,
    backend_command: _BackendCommand | None,
) -> _LoopbackBackend:
    if backend_command is None:
        if configured_backend is None:
            raise _BackendCommandError()
        return configured_backend
    command_backend = _backend_from_command(backend_command)
    if configured_backend is not None and configured_backend != command_backend:
        raise _BackendCommandError()
    return command_backend if configured_backend is None else configured_backend


def _parse_arguments(argv: list[str] | None) -> _ProxyArguments:
    parser = argparse.ArgumentParser(
        description="Serve an authenticated loopback proxy for a local OpenAI-compatible backend.",
    )
    parser.add_argument(
        "--listen-port",
        type=_parse_port,
        required=True,
        help="proxy port; the listener is fixed to 127.0.0.1",
    )
    parser.add_argument(
        "--backend-url",
        type=_parse_backend_url,
        help="literal loopback root URL for an already-running backend, for example http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--backend-command",
        nargs=argparse.REMAINDER,
        metavar="COMMAND",
        help=(
            "start a vLLM backend child; this option consumes the remaining arguments and requires matching "
            "explicit --host and --port values"
        ),
    )
    parser.add_argument(
        "--backend-timeout-seconds",
        type=_parse_timeout,
        default=_DEFAULT_BACKEND_TIMEOUT_SECONDS,
        help="maximum idle socket operation time while connecting to or reading from the backend (default: 300)",
    )
    parser.add_argument(
        "--backend-startup-timeout-seconds",
        type=_parse_backend_startup_timeout,
        default=_DEFAULT_BACKEND_STARTUP_TIMEOUT_SECONDS,
        help="maximum wait for a launched backend to accept loopback connections (default: 300)",
    )
    parsed = parser.parse_args(argv)
    try:
        backend_command = _validated_backend_command(parsed.backend_command)
        backend = _resolve_backend(parsed.backend_url, backend_command)
    except _BackendCommandError:
        parser.error(
            "provide --backend-url or a --backend-command with one matching literal loopback --host and --port"
        )
    return _ProxyArguments(
        listen_port=parsed.listen_port,
        backend=backend,
        backend_command=backend_command,
        backend_timeout_seconds=parsed.backend_timeout_seconds,
        backend_startup_timeout_seconds=parsed.backend_startup_timeout_seconds,
    )


def _load_bearer_token() -> bytes:
    """Load one strict token from the protected file selected by the environment.

    This intentionally has no fallback to an argument, stdin, a conventional
    filename, or a second environment variable.  A POSIX target with an exact
    owner-only file is required, matching the runtime handoff contract.
    """

    token_file_value = os.environ.get(_TOKEN_FILE_ENVIRONMENT_NAME)
    if not token_file_value:
        raise _StartupError()
    try:
        token_file = Path(token_file_value)
    except (TypeError, ValueError):
        raise _StartupError() from None
    if not token_file.is_absolute() or os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise _StartupError()

    descriptor: int | None = None
    try:
        before = os.stat(token_file, follow_symlinks=False)
        _require_private_token_file(before)
        descriptor = os.open(
            token_file,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        after = os.fstat(descriptor)
        _require_private_token_file(after)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise _StartupError()
        payload = _read_bounded_token_file(descriptor)
    except _StartupError:
        raise
    except (OSError, ValueError):
        raise _StartupError() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise _StartupError()
    token = payload[:-1]
    if not _TOKEN_PATTERN.fullmatch(token):
        raise _StartupError()
    return token


def _require_private_token_file(file_stat: os.stat_result) -> None:
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or not hasattr(os, "geteuid")
        or file_stat.st_uid != os.geteuid()
        or stat.S_IMODE(file_stat.st_mode) != _TOKEN_FILE_MODE
    ):
        raise _StartupError()


def _read_bounded_token_file(descriptor: int) -> bytes:
    """Read no more than one token plus its newline, rejecting trailing bytes."""

    maximum_payload_bytes = _MAX_TOKEN_BYTES + 1
    chunks: list[bytes] = []
    total = 0
    while total <= maximum_payload_bytes:
        chunk = os.read(descriptor, maximum_payload_bytes + 1 - total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > maximum_payload_bytes or os.read(descriptor, 1):
        raise _StartupError()
    return b"".join(chunks)


def _has_valid_authorization(headers: object, expected_token: bytes) -> bool:
    """Accept exactly one RFC-shaped Bearer field without retaining its text."""

    get_all = getattr(headers, "get_all", None)
    if not callable(get_all):
        return False
    values = get_all("Authorization")
    if not isinstance(values, list) or len(values) != 1:
        return False
    value = values[0]
    if not isinstance(value, str):
        return False
    pieces = value.split(" ")
    if len(pieces) != 2 or pieces[0].casefold() != "bearer" or not pieces[1]:
        return False
    try:
        candidate = pieces[1].encode("ascii")
    except UnicodeEncodeError:
        return False
    return bool(_TOKEN_PATTERN.fullmatch(candidate)) and hmac.compare_digest(candidate, expected_token)


def _request_content_length(handler: BaseHTTPRequestHandler) -> int:
    transfer_encoding = handler.headers.get_all("Transfer-Encoding")
    if transfer_encoding:
        raise _ClientRequestError(HTTPStatus.NOT_IMPLEMENTED)

    values = handler.headers.get_all("Content-Length")
    if values is None:
        if handler.command in _BODY_METHODS:
            raise _ClientRequestError(HTTPStatus.LENGTH_REQUIRED)
        return 0
    if len(values) != 1:
        raise _ClientRequestError(HTTPStatus.BAD_REQUEST)
    raw_value = values[0]
    if not isinstance(raw_value, str) or raw_value != raw_value.strip() or not raw_value.isascii() or not raw_value.isdecimal():
        raise _ClientRequestError(HTTPStatus.BAD_REQUEST)
    try:
        return int(raw_value)
    except ValueError:
        raise _ClientRequestError(HTTPStatus.BAD_REQUEST) from None


def _request_target(handler: BaseHTTPRequestHandler) -> str:
    target = handler.path
    if not isinstance(target, str) or not target.startswith("/") or target.startswith("//"):
        raise _ClientRequestError(HTTPStatus.BAD_REQUEST)
    return target


def _header_pairs(headers: object) -> list[tuple[str, str]]:
    items = getattr(headers, "items", None)
    if not callable(items):
        raise _ClientRequestError(HTTPStatus.BAD_REQUEST)
    pairs = list(items())
    for name, value in pairs:
        if not _is_safe_header(name, value):
            raise _ClientRequestError(HTTPStatus.BAD_REQUEST)
    return pairs


def _is_safe_header(name: object, value: object) -> bool:
    if not isinstance(name, str) or not _HEADER_NAME_PATTERN.fullmatch(name) or not isinstance(value, str):
        return False
    return not any(ord(character) < 32 and character != "\t" or ord(character) == 127 for character in value)


def _connection_header_names(headers: list[tuple[str, str]]) -> frozenset[str]:
    names: set[str] = set()
    for name, value in headers:
        if name.casefold() == "connection":
            names.update(token.strip().casefold() for token in value.split(",") if token.strip())
    return frozenset(names)


def _forwardable_request_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    blocked = _HOP_BY_HOP_HEADERS | _connection_header_names(headers) | {
        "authorization",
        "content-length",
        "expect",
        "host",
    }
    return [(name, value) for name, value in headers if name.casefold() not in blocked]


def _forwardable_response_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    blocked = _HOP_BY_HOP_HEADERS | _connection_header_names(headers) | {"content-length"}
    return [(name, value) for name, value in headers if _is_safe_header(name, value) and name.casefold() not in blocked]


def _response_content_length(headers: list[tuple[str, str]]) -> int | None:
    if any(name.casefold() == "transfer-encoding" for name, _ in headers):
        return None
    values = [value for name, value in headers if name.casefold() == "content-length"]
    if len(values) != 1:
        return None
    value = values[0]
    if value != value.strip() or not value.isascii() or not value.isdecimal():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _response_has_body(method: str, status: int) -> bool:
    return method != "HEAD" and status not in {HTTPStatus.NO_CONTENT, HTTPStatus.NOT_MODIFIED} and not 100 <= status < 200


class _OpenAIProxyServer(ThreadingHTTPServer):
    """A silent threaded server whose private state never represents the token."""

    address_family = socket.AF_INET
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port: int, backend: _LoopbackBackend, token: bytes, backend_timeout: float) -> None:
        self._backend = backend
        self._token = token
        self._backend_timeout = backend_timeout
        super().__init__(("127.0.0.1", port), _OpenAIProxyHandler)

    def clear_token(self) -> None:
        """Drop the server's reference when its listener is closed."""

        self._token = b""

    def handle_error(self, request: object, client_address: object) -> None:
        """Do not emit request paths, headers, exceptions, or secrets to stderr."""

    def __repr__(self) -> str:
        return "_OpenAIProxyServer(<redacted>)"


class _OpenAIProxyHandler(BaseHTTPRequestHandler):
    """HTTP/1.1 request handler that strips proxy credentials before forwarding."""

    protocol_version = "HTTP/1.1"
    server: _OpenAIProxyServer

    def do_GET(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_CONNECT(self) -> None:  # noqa: N802
        self._unsupported_method()

    def do_TRACE(self) -> None:  # noqa: N802
        self._unsupported_method()

    def handle_expect_100(self) -> bool:
        """Authenticate before asking a client to transmit an expected request body."""

        if not self._authorized():
            self._emit_unauthorized()
            return False
        try:
            _request_content_length(self)
        except _ClientRequestError as error:
            self._emit_request_error(error.status)
            return False
        self.send_response_only(HTTPStatus.CONTINUE)
        self.end_headers()
        return True

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Replace BaseHTTPRequestHandler's reflective HTML and access logging."""

        del message, explain
        if self._authorized():
            self._emit_request_error(HTTPStatus.BAD_REQUEST)
        else:
            self._emit_unauthorized()

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """Suppress default request logs, which may otherwise include request targets."""

    def log_error(self, message_format: str, *args: object) -> None:
        """Suppress default error logs, which may otherwise include request fields."""

    def log_message(self, message_format: str, *args: object) -> None:
        """Suppress default access logs, which may otherwise include request targets."""

    def _authorized(self) -> bool:
        return _has_valid_authorization(getattr(self, "headers", None), self.server._token)

    def _unsupported_method(self) -> None:
        if not self._authorized():
            self._emit_unauthorized()
            return
        self._emit_error(
            HTTPStatus.METHOD_NOT_ALLOWED,
            error_type="invalid_request_error",
            code="method_not_allowed",
            message="This HTTP method is not supported by the local model proxy.",
        )

    def _proxy_request(self) -> None:
        if not self._authorized():
            self._emit_unauthorized()
            return
        self._response_started = False
        try:
            target = _request_target(self)
            content_length = _request_content_length(self)
            request_headers = _header_pairs(self.headers)
        except _ClientRequestError as error:
            self._emit_request_error(error.status)
            return

        connection = http.client.HTTPConnection(
            self.server._backend.host,
            self.server._backend.port,
            timeout=self.server._backend_timeout,
        )
        try:
            self._send_backend_request(connection, target, request_headers, content_length)
            response = connection.getresponse()
            self._relay_backend_response(response)
        except _ClientRequestError as error:
            if self._response_can_receive_error():
                self._emit_request_error(error.status)
        except _BackendProtocolError:
            if self._response_can_receive_error():
                self._emit_backend_unavailable()
        except (http.client.HTTPException, OSError, TimeoutError):
            if self._response_can_receive_error():
                self._emit_backend_unavailable()
        finally:
            connection.close()

    def _response_can_receive_error(self) -> bool:
        if self._response_started:
            self.close_connection = True
            return False
        return True

    def _send_backend_request(
        self,
        connection: http.client.HTTPConnection,
        target: str,
        request_headers: list[tuple[str, str]],
        content_length: int,
    ) -> None:
        connection.putrequest(self.command, target, skip_host=True, skip_accept_encoding=True)
        for name, value in _forwardable_request_headers(request_headers):
            connection.putheader(name, value)
        connection.putheader("Host", self.server._backend.host_header)
        connection.putheader("Connection", "close")
        connection.putheader("Content-Length", str(content_length))
        connection.endheaders()

        remaining = content_length
        while remaining:
            chunk = self.rfile.read(min(_STREAM_CHUNK_BYTES, remaining))
            if not chunk:
                raise _ClientRequestError(HTTPStatus.BAD_REQUEST)
            connection.send(chunk)
            remaining -= len(chunk)

    def _relay_backend_response(self, response: http.client.HTTPResponse) -> None:
        if response.status == HTTPStatus.SWITCHING_PROTOCOLS:
            raise _BackendProtocolError()

        response_headers = response.getheaders()
        content_length = _response_content_length(response_headers)
        has_body = _response_has_body(self.command, response.status)
        use_chunked_response = has_body and content_length is None and self.request_version == "HTTP/1.1"

        self.send_response_only(response.status)
        for name, value in _forwardable_response_headers(response_headers):
            self.send_header(name, value)
        if content_length is not None and (has_body or self.command == "HEAD"):
            self.send_header("Content-Length", str(content_length))
        elif use_chunked_response:
            self.send_header("Transfer-Encoding", "chunked")
        elif has_body:
            self.send_header("Connection", "close")
            self.close_connection = True
        self._response_started = True
        self.end_headers()
        self.wfile.flush()

        if not has_body:
            return
        if use_chunked_response:
            self._stream_chunked_response(response)
        else:
            self._stream_raw_response(response)

    def _stream_chunked_response(self, response: http.client.HTTPResponse) -> None:
        while chunk := response.read(_STREAM_CHUNK_BYTES):
            self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
            self.wfile.write(chunk)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _stream_raw_response(self, response: http.client.HTTPResponse) -> None:
        while chunk := response.read(_STREAM_CHUNK_BYTES):
            self.wfile.write(chunk)
            self.wfile.flush()

    def _emit_unauthorized(self) -> None:
        self._emit_error(
            HTTPStatus.UNAUTHORIZED,
            error_type="authentication_error",
            code="invalid_api_key",
            message="Authentication is required for the local model proxy.",
            challenge=True,
            close=True,
        )

    def _emit_request_error(self, status: HTTPStatus) -> None:
        code = "request_body_not_supported" if status == HTTPStatus.NOT_IMPLEMENTED else "invalid_request"
        self._emit_error(
            status,
            error_type="invalid_request_error",
            code=code,
            message="The local model proxy could not accept this request.",
            close=True,
        )

    def _emit_backend_unavailable(self) -> None:
        self._emit_error(
            HTTPStatus.BAD_GATEWAY,
            error_type="server_error",
            code="backend_unavailable",
            message="The local model backend is unavailable.",
            close=True,
        )

    def _emit_error(
        self,
        status: HTTPStatus,
        *,
        error_type: str,
        code: str,
        message: str,
        challenge: bool = False,
        close: bool = True,
    ) -> None:
        """Send a non-reflective OpenAI-shaped JSON error without access logging."""

        payload = json.dumps(
            {
                "error": {
                    "message": message,
                    "type": error_type,
                    "param": None,
                    "code": code,
                }
            },
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            self.send_response_only(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            if challenge:
                self.send_header("WWW-Authenticate", "Bearer")
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
                self.wfile.flush()
        except (OSError, ValueError):
            self.close_connection = True

    def __repr__(self) -> str:
        return "_OpenAIProxyHandler(<redacted>)"


def _reject_token_in_backend_command(command: _BackendCommand, token: bytes) -> None:
    """Refuse a caller-supplied command that would expose this proxy's token."""

    try:
        token_text = token.decode("ascii")
    except UnicodeDecodeError:
        raise _BackendStartupError() from None
    if any(token_text in argument for argument in command.arguments):
        raise _BackendStartupError()


def _launch_backend(command: _BackendCommand, token: bytes) -> subprocess.Popen[bytes]:
    """Launch one non-shell child in the proxy's existing process group.

    The child deliberately does not inherit the token-file environment variable:
    it has no reason to authenticate proxy clients and must never receive the
    bearer handoff.  ``start_new_session`` remains false so the target
    supervisor still owns one process group for this whole generation.
    """

    _reject_token_in_backend_command(command, token)
    environment = dict(os.environ)
    environment.pop(_TOKEN_FILE_ENVIRONMENT_NAME, None)
    try:
        return subprocess.Popen(
            command.arguments,
            stdin=subprocess.DEVNULL,
            env=environment,
            close_fds=True,
            start_new_session=False,
        )
    except (OSError, ValueError):
        raise _BackendStartupError() from None


def _wait_for_backend_connectivity(
    backend: _LoopbackBackend,
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> None:
    """Wait only for the launched child to expose its declared loopback port."""

    deadline = time.monotonic() + timeout_seconds
    while True:
        if process.poll() is not None:
            raise _BackendStartupError()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _BackendStartupError()
        try:
            with socket.create_connection(
                (backend.host, backend.port),
                timeout=min(1.0, remaining),
            ):
                if process.poll() is None:
                    return
        except OSError:
            pass
        sleep_seconds = min(_BACKEND_CONNECT_RETRY_SECONDS, deadline - time.monotonic())
        if sleep_seconds <= 0:
            raise _BackendStartupError()
        time.sleep(sleep_seconds)


def _terminate_and_reap_backend(process: subprocess.Popen[bytes]) -> None:
    """Stop and reap the direct child without printing its command or status."""

    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=_BACKEND_STOP_TIMEOUT_SECONDS)
            return
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
        except OSError:
            pass
    try:
        process.wait(timeout=_BACKEND_STOP_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=_BACKEND_STOP_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _serve_with_backend_supervision(
    server: _OpenAIProxyServer,
    process: subprocess.Popen[bytes] | None,
) -> int:
    """Serve until interrupted, or until the optional direct backend child exits."""

    if process is None:
        server.serve_forever()
        return 0
    server.timeout = _BACKEND_SUPERVISION_POLL_SECONDS
    while process.poll() is None:
        server.handle_request()
    return 1


def _termination_interrupt(_signum: int, _frame: object) -> None:
    """Turn SIGTERM into normal cleanup so the direct child is reaped."""

    raise KeyboardInterrupt


def _install_termination_handler() -> tuple[bool, object | None]:
    """Install a POSIX SIGTERM cleanup path without making it a platform dependency."""

    if os.name != "posix":
        return False, None
    try:
        previous = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _termination_interrupt)
    except (OSError, RuntimeError, ValueError):
        return False, None
    return True, previous


def _restore_termination_handler(installed: bool, previous: object | None) -> None:
    if not installed:
        return
    try:
        signal.signal(signal.SIGTERM, previous)
    except (OSError, RuntimeError, ValueError, TypeError):
        pass


def _write_startup_error(message: str) -> None:
    """Emit a fixed diagnostic that contains neither the token nor its file path."""

    try:
        sys.stderr.write(f"openai-proxy: {message}\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    """Run the loopback proxy until interrupted or its server loop ends."""

    arguments = _parse_arguments(argv)
    try:
        token = _load_bearer_token()
    except _StartupError:
        _write_startup_error("protected bearer-token handoff is unavailable")
        return 2

    backend_process: subprocess.Popen[bytes] | None = None
    server: _OpenAIProxyServer | None = None
    handler_installed, previous_handler = _install_termination_handler()
    try:
        if arguments.backend_command is not None:
            backend_process = _launch_backend(arguments.backend_command, token)
            _wait_for_backend_connectivity(
                arguments.backend,
                backend_process,
                arguments.backend_startup_timeout_seconds,
            )
        try:
            server = _OpenAIProxyServer(
                arguments.listen_port,
                arguments.backend,
                token,
                arguments.backend_timeout_seconds,
            )
        except OSError:
            _write_startup_error("unable to bind the loopback proxy listener")
            return 2
        try:
            return _serve_with_backend_supervision(server, backend_process)
        except KeyboardInterrupt:
            return 0
        except OSError:
            _write_startup_error("the loopback proxy listener stopped unexpectedly")
            return 1
    except _BackendStartupError:
        _write_startup_error("launched backend did not become reachable on loopback")
        return 2
    except KeyboardInterrupt:
        return 0
    finally:
        if server is not None:
            try:
                server.server_close()
            except OSError:
                pass
            server.clear_token()
        if backend_process is not None:
            _terminate_and_reap_backend(backend_process)
        _restore_termination_handler(handler_installed, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
