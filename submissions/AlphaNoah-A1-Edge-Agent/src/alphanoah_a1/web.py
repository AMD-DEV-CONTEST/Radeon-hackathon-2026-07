"""Local-only standard-library Web entry for QR incident reporting."""

from __future__ import annotations

import argparse
import html
import secrets
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from .models import Event
from .qr_input import (
    ALLOWED_FORM_FIELDS,
    DEFAULT_EVENT_TYPE,
    FIELD_LIMITS,
    IncidentReportInputError,
    QRIncidentInputAdapter,
)
from .runtime import AlphaNoahRuntime

LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
MAX_REQUEST_BODY_BYTES = 16 * 1024
MAX_FORM_FIELDS = 10
REQUEST_READ_TIMEOUT_SECONDS = 5.0
SUBMISSION_TOKEN_TTL_SECONDS = 30 * 60
MAX_SUBMISSION_TOKENS = 1000
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = REPOSITORY_ROOT / "tmp" / "alphanoah_qr_demo.sqlite3"


class SubmissionGuard:
    """In-memory one-time tokens that prevent accidental duplicate POSTs."""

    def __init__(
        self,
        *,
        ttl_seconds: int = SUBMISSION_TOKEN_TTL_SECONDS,
        max_tokens: int = MAX_SUBMISSION_TOKENS,
    ):
        self.ttl_seconds = ttl_seconds
        self.max_tokens = max_tokens
        self._tokens: dict[str, tuple[float, bool]] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            while len(self._tokens) >= self.max_tokens:
                oldest = min(
                    self._tokens,
                    key=lambda token: self._tokens[token][0],
                )
                del self._tokens[oldest]
            token = secrets.token_urlsafe(24)
            while token in self._tokens:
                token = secrets.token_urlsafe(24)
            self._tokens[token] = (now, False)
            return token

    def claim(self, token: str) -> str:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            record = self._tokens.get(token)
            if record is None:
                return "invalid"
            if record[1]:
                return "duplicate"
            self._tokens[token] = (record[0], True)
            return "accepted"

    def _prune(self, now: float) -> None:
        expired = [
            token
            for token, (issued_at, _) in self._tokens.items()
            if now - issued_at > self.ttl_seconds
        ]
        for token in expired:
            del self._tokens[token]


class QRIncidentHTTPServer(ThreadingHTTPServer):
    """Threaded loopback-only server with injected adapter state."""

    allow_reuse_address = True
    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        server_address: tuple[str, int],
        adapter: QRIncidentInputAdapter,
        submission_guard: SubmissionGuard | None = None,
    ):
        if server_address[0] != LOCAL_HOST:
            raise ValueError(f"QR demo server must bind to {LOCAL_HOST}")
        self.adapter = adapter
        self.submission_guard = submission_guard or SubmissionGuard()
        super().__init__(server_address, QRIncidentRequestHandler)

    def get_request(self) -> tuple[Any, Any]:
        request, client_address = super().get_request()
        request.settimeout(REQUEST_READ_TIMEOUT_SECONDS)
        return request, client_address

    def handle_error(
        self, request: Any, client_address: tuple[str, int]
    ) -> None:
        """Avoid leaking tracebacks, local paths or request data to stderr."""

        print("AlphaNoah local demo request handling failed.", file=sys.stderr)


class QRIncidentRequestHandler(BaseHTTPRequestHandler):
    """Serve one bounded HTML form and submit it through the input adapter."""

    server: QRIncidentHTTPServer
    server_version = "AlphaNoahLocalDemo"
    sys_version = ""

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != "/report":
            self._send_message(
                HTTPStatus.NOT_FOUND,
                "Not found",
                "The requested local demo page does not exist.",
            )
            return
        try:
            query_fields = parse_qs(
                parsed.query,
                keep_blank_values=True,
                max_num_fields=MAX_FORM_FIELDS,
            )
            prefill = self.server.adapter.validate_prefill(query_fields)
        except (ValueError, IncidentReportInputError):
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid report URL",
                "The QR URL contains invalid or unsupported fields.",
            )
            return

        values = {
            "asset_id": prefill["asset_id"],
            "location": prefill["location"],
            "event_type": DEFAULT_EVENT_TYPE,
            "reporter": "",
            "description": "",
            "attachments": "",
        }
        self._send_html(
            HTTPStatus.OK,
            _render_form(
                values,
                submission_token=self.server.submission_guard.issue(),
            ),
        )

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != "/report" or parsed.query:
            self._send_message(
                HTTPStatus.NOT_FOUND,
                "Not found",
                "Incident submissions are accepted only at /report.",
            )
            return

        if self.headers.get_all("Transfer-Encoding", []):
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid request",
                "Transfer-Encoding is not supported by this local demo.",
            )
            return

        content_type_headers = self.headers.get_all("Content-Type", [])
        if len(content_type_headers) > 1:
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid request",
                "Content-Type must be submitted exactly once.",
            )
            return
        content_type = self.headers.get_content_type()
        charset = self.headers.get_content_charset()
        if content_type != "application/x-www-form-urlencoded":
            self._send_message(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "Unsupported request",
                "Only HTML form submissions are accepted.",
            )
            return
        if charset not in (None, "utf-8"):
            self._send_message(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "Unsupported request",
                "Form submissions must use UTF-8.",
            )
            return

        content_length_headers = self.headers.get_all("Content-Length", [])
        if not content_length_headers:
            self._send_message(
                HTTPStatus.LENGTH_REQUIRED,
                "Length required",
                "A bounded Content-Length header is required.",
            )
            return
        if len(content_length_headers) != 1:
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid request",
                "Content-Length must be submitted exactly once.",
            )
            return
        content_length_header = content_length_headers[0]
        if (
            not content_length_header.isascii()
            or not content_length_header.isdecimal()
            or len(content_length_header) > 20
        ):
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid request",
                "Content-Length must contain only decimal digits.",
            )
            return
        content_length = int(content_length_header)
        if content_length > MAX_REQUEST_BODY_BYTES:
            self._send_message(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "Request too large",
                "The incident report exceeds the local demo size limit.",
            )
            return

        try:
            body = self.rfile.read(content_length)
        except TimeoutError:
            self._send_message(
                HTTPStatus.REQUEST_TIMEOUT,
                "Request timed out",
                "The incident form body was not received in time.",
            )
            return
        except OSError:
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid request",
                "The incident form body could not be read.",
            )
            return
        if len(body) != content_length:
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid request",
                "The incident form body is incomplete.",
            )
            return
        try:
            form_fields = parse_qs(
                body.decode("utf-8", errors="strict"),
                keep_blank_values=True,
                max_num_fields=MAX_FORM_FIELDS,
            )
        except (UnicodeDecodeError, ValueError):
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid request",
                "The incident form could not be parsed.",
            )
            return

        try:
            submission_token = _pop_single_value(
                form_fields, "submission_token"
            )
        except IncidentReportInputError:
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid submission",
                "The submission token is missing or invalid.",
            )
            return

        claim = self.server.submission_guard.claim(submission_token)
        if claim == "duplicate":
            self._send_message(
                HTTPStatus.CONFLICT,
                "Duplicate submission",
                "This form was already submitted. Reload the report page.",
            )
            return
        if claim != "accepted":
            self._send_message(
                HTTPStatus.BAD_REQUEST,
                "Invalid submission",
                "Reload the report page before submitting.",
            )
            return

        try:
            event = self.server.adapter.submit(form_fields)
        except IncidentReportInputError as exc:
            values = _safe_form_values(form_fields)
            self._send_html(
                HTTPStatus.BAD_REQUEST,
                _render_form(
                    values,
                    submission_token=self.server.submission_guard.issue(),
                    error=str(exc),
                ),
            )
            return
        except Exception:
            self._send_message(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Submission failed",
                "The local incident record could not be created.",
            )
            return

        self._send_html(
            HTTPStatus.CREATED,
            _render_success(event),
        )

    def do_HEAD(self) -> None:
        self._method_not_allowed(write_body=False)

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress request/header logging in the bounded local demo."""

    def version_string(self) -> str:
        return self.server_version

    def _method_not_allowed(self, *, write_body: bool = True) -> None:
        self._send_message(
            HTTPStatus.METHOD_NOT_ALLOWED,
            "Method not allowed",
            "Only GET and POST are supported by this local demo.",
            write_body=write_body,
            extra_headers={"Allow": "GET, POST"},
        )

    def _send_message(
        self,
        status: HTTPStatus,
        title: str,
        message: str,
        *,
        write_body: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        content = (
            f"<h1>{html.escape(title)}</h1>"
            f"<p>{html.escape(message)}</p>"
            '<p><a href="/report">Return to the incident form</a></p>'
        )
        self._send_html(
            status,
            _layout(title, content),
            write_body=write_body,
            extra_headers=extra_headers,
        )

    def _send_html(
        self,
        status: HTTPStatus,
        document: str,
        *,
        write_body: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = document.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if write_body:
            self.wfile.write(body)


def _pop_single_value(
    form_fields: dict[str, list[str]],
    name: str,
) -> str:
    values = form_fields.pop(name, None)
    if (
        values is None
        or len(values) != 1
        or not isinstance(values[0], str)
        or not values[0].strip()
        or len(values[0]) > 128
    ):
        raise IncidentReportInputError(f"{name} is invalid.")
    return values[0].strip()


def _safe_form_values(
    form_fields: dict[str, list[str]],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in ALLOWED_FORM_FIELDS:
        raw_values = form_fields.get(name, [])
        values[name] = (
            raw_values[0]
            if len(raw_values) == 1 and isinstance(raw_values[0], str)
            else ""
        )
    values["event_type"] = values["event_type"] or DEFAULT_EVENT_TYPE
    return values


def _render_form(
    values: dict[str, str],
    *,
    submission_token: str,
    error: str = "",
) -> str:
    escaped = {
        name: html.escape(str(values.get(name, "")), quote=True)
        for name in ALLOWED_FORM_FIELDS
    }
    escaped_token = html.escape(submission_token, quote=True)
    error_html = (
        f'<p class="error">{html.escape(error)}</p>' if error else ""
    )
    content = f"""
<h1>AlphaNoah Industrial Incident Report</h1>
<h2>AlphaNoah 工业现场问题申报</h2>
<p>This prototype creates an incident record. It does not automatically
diagnose equipment faults.</p>
<p>该原型仅创建问题记录并进入处理闭环，当前不会自动完成设备故障诊断。</p>
<p class="notice">Synthetic demo data · Not a real production incident</p>
{error_html}
<form method="post" action="/report">
  <input type="hidden" name="submission_token" value="{escaped_token}">
  <label>Asset ID / 设备编号
    <input name="asset_id" maxlength="{FIELD_LIMITS['asset_id']}"
           value="{escaped['asset_id']}">
  </label>
  <label>Location / 现场位置
    <input name="location" maxlength="{FIELD_LIMITS['location']}"
           value="{escaped['location']}">
  </label>
  <label>Event type / 事件类型
    <input name="event_type" maxlength="{FIELD_LIMITS['event_type']}"
           value="{escaped['event_type']}" required>
  </label>
  <label>Reporter / 报告人（可选）
    <input name="reporter" maxlength="{FIELD_LIMITS['reporter']}"
           value="{escaped['reporter']}">
  </label>
  <label>Description / 问题描述
    <textarea name="description" maxlength="{FIELD_LIMITS['description']}"
              required>{escaped['description']}</textarea>
  </label>
  <label>Attachment references / 附件引用（可选，每行一个）
    <textarea name="attachments"
              maxlength="{FIELD_LIMITS['attachments']}">{escaped['attachments']}</textarea>
  </label>
  <button type="submit">Submit incident / 提交问题</button>
</form>
"""
    return _layout("AlphaNoah Industrial Incident Report", content)


def _render_success(event: Event) -> str:
    values = {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "asset_id": event.asset_id,
        "location": event.location,
        "description": event.description,
        "status": event.status.value,
        "timestamp": event.timestamp,
    }
    escaped = {
        name: html.escape(str(value), quote=True)
        for name, value in values.items()
    }
    event_command = html.escape(
        "python -m alphanoah_a1.demo --db <same-database-file> "
        f"show event {event.event_id}"
    )
    trace_command = html.escape(
        "python -m alphanoah_a1.demo --db <same-database-file> "
        f"show trace {event.trace_id}"
    )
    content = f"""
<h1>事件已提交</h1>
<p>The incident record was created. No equipment diagnosis was performed.</p>
<dl>
  <dt>Event ID</dt><dd>{escaped['event_id']}</dd>
  <dt>Trace ID</dt><dd>{escaped['trace_id']}</dd>
  <dt>Asset ID</dt><dd>{escaped['asset_id']}</dd>
  <dt>Location</dt><dd>{escaped['location']}</dd>
  <dt>Description</dt><dd>{escaped['description']}</dd>
  <dt>Status</dt><dd>{escaped['status']}</dd>
  <dt>Created</dt><dd>{escaped['timestamp']}</dd>
</dl>
<p>该问题已经进入 AlphaNoah 事件处理流程。</p>
<p>使用启动服务时选择的同一数据库路径执行：</p>
<pre>{event_command}
{trace_command}</pre>
<p><a href="/report">Submit another synthetic incident</a></p>
"""
    return _layout("Incident submitted", content)


def _layout(title: str, content: str) -> str:
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 46rem;
            margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    label {{ display: block; margin: 1rem 0; font-weight: 600; }}
    input, textarea {{ display: block; box-sizing: border-box; width: 100%;
                       margin-top: .35rem; padding: .65rem; font: inherit; }}
    textarea {{ min-height: 6rem; }}
    button {{ padding: .7rem 1.1rem; font: inherit; cursor: pointer; }}
    .notice {{ padding: .65rem; background: #fff4cc; }}
    .error {{ padding: .65rem; color: #8b0000; background: #ffe8e8; }}
    dt {{ font-weight: 700; margin-top: .6rem; }}
    dd {{ margin-left: 0; overflow-wrap: anywhere; }}
    pre {{ padding: .75rem; background: #f3f3f3; overflow-x: auto; }}
  </style>
</head>
<body>
{content}
</body>
</html>
"""


def create_server(
    database_path: str | Path,
    *,
    port: int = DEFAULT_PORT,
) -> QRIncidentHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    runtime = AlphaNoahRuntime(str(database_path))
    adapter = QRIncidentInputAdapter(runtime)
    return QRIncidentHTTPServer((LOCAL_HOST, port), adapter)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local-only AlphaNoah QR incident report demo."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    server = create_server(args.db, port=args.port)
    actual_port = server.server_address[1]
    query = urlencode(
        {"asset_id": "PACK-003", "location": "Packaging-Line-A"}
    )
    print("AlphaNoah QR incident reporting demo")
    print(f"Listening on http://{LOCAL_HOST}:{actual_port}/report")
    print(f"Demo URL: http://{LOCAL_HOST}:{actual_port}/report?{query}")
    print("Localhost only. Synthetic demo data. No equipment diagnosis.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Stopping local incident reporting demo.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
