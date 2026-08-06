"""Local-only standard-library JSON API over the Task 05C-1 Web adapter."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .demo_activation import build_demo_activation_application
from .demo_activation_adapter import DemoActivationWebAdapter
from .golden_path import (
    RestaurantAirconGoldenPath,
    build_restaurant_aircon_golden_path,
)
from .provider_config import DEFAULT_CONFIG_FILENAME, ProviderKind
from .provider_orchestration import (
    ProviderRuntimeOrchestrator,
    ResolvedProviderRuntime,
    StartupProviderOptions,
    UnavailableAnalysisProvider,
)
from .runtime_projection import RuntimeProjectionWebAdapter
from .web_adapter import (
    RestaurantAirconWebAdapter,
    WebAdapterError,
    WebErrorCode,
)

LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8090
MAX_REQUEST_BODY_BYTES = 16 * 1024
REQUEST_READ_TIMEOUT_SECONDS = 5.0
MAX_REQUEST_TARGET_LENGTH = 2_048
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = REPOSITORY_ROOT / "tmp" / "alphanoah_web_api.sqlite3"
DEFAULT_AI_RUNTIME_CONFIG = REPOSITORY_ROOT / DEFAULT_CONFIG_FILENAME


class WebAdapterHTTPServer(ThreadingHTTPServer):
    """Threaded loopback server containing only the injected Web adapter."""

    allow_reuse_address = True
    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        server_address: tuple[str, int],
        adapter: RestaurantAirconWebAdapter,
        demo_adapter: DemoActivationWebAdapter | None = None,
        projection_adapter: RuntimeProjectionWebAdapter | None = None,
        provider_runtime: ResolvedProviderRuntime | None = None,
        static_directory: str | Path | None = None,
    ):
        if server_address[0] != LOCAL_HOST:
            raise ValueError(f"Web Adapter server must bind to {LOCAL_HOST}")
        if not isinstance(adapter, RestaurantAirconWebAdapter):
            raise TypeError("adapter must be RestaurantAirconWebAdapter")
        if demo_adapter is not None and not isinstance(
            demo_adapter,
            DemoActivationWebAdapter,
        ):
            raise TypeError(
                "demo_adapter must be DemoActivationWebAdapter or None"
            )
        if projection_adapter is not None and not isinstance(
            projection_adapter,
            RuntimeProjectionWebAdapter,
        ):
            raise TypeError(
                "projection_adapter must be "
                "RuntimeProjectionWebAdapter or None"
            )
        self.adapter = adapter
        self.demo_adapter = demo_adapter
        self.projection_adapter = projection_adapter
        self.provider_runtime = provider_runtime
        self.static_directory = (
            Path(static_directory).resolve()
            if static_directory is not None
            else None
        )
        super().__init__(server_address, WebAdapterRequestHandler)

    def get_request(self) -> tuple[Any, Any]:
        request, client_address = super().get_request()
        request.settimeout(REQUEST_READ_TIMEOUT_SECONDS)
        return request, client_address

    def handle_error(
        self,
        request: Any,
        client_address: tuple[str, int],
    ) -> None:
        """Never print a traceback, request body, path, or local resource."""

        print(
            "AlphaNoah Web Adapter request handling failed.",
            file=sys.stderr,
        )


class WebAdapterRequestHandler(BaseHTTPRequestHandler):
    """Translate bounded HTTP/JSON requests into Web adapter calls."""

    server: WebAdapterHTTPServer
    server_version = "AlphaNoahWebAdapter"
    sys_version = ""

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def do_HEAD(self) -> None:
        self._method_not_allowed()

    def log_message(self, format: str, *args: object) -> None:
        """Disable request logs so headers and user input are never recorded."""

    def _dispatch(self, method: str) -> None:
        try:
            if len(self.path) > MAX_REQUEST_TARGET_LENGTH:
                raise WebAdapterError(
                    WebErrorCode.INVALID_REQUEST,
                    "Request target is too long.",
                    HTTPStatus.REQUEST_URI_TOO_LONG,
                )
            parsed = urlsplit(self.path)
            if parsed.query:
                raise WebAdapterError(
                    WebErrorCode.INVALID_REQUEST,
                    "Query parameters are not supported by this API.",
                    HTTPStatus.BAD_REQUEST,
                )
            parts = tuple(part for part in parsed.path.split("/") if part)
            if method == "GET" and (not parts or parts[0] != "api"):
                self._serve_static(parsed.path)
                return
            if method == "GET":
                status, result = self._handle_get(parts)
            else:
                payload = self._read_json_body()
                status, result = self._handle_post(parts, payload)
            self._send_json(status, result)
        except WebAdapterError as exc:
            self._send_json(exc.status, exc.to_dict())
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error_code": WebErrorCode.INTERNAL_ERROR.value,
                    "message": "The Web Adapter could not complete the request.",
                },
            )

    def _serve_static(self, request_path: str) -> None:
        root = self.server.static_directory
        if root is None:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Static frontend is not configured.",
                HTTPStatus.NOT_FOUND,
            )
        relative = request_path.lstrip("/") or "index.html"
        candidate = (root / relative).resolve()
        if root not in candidate.parents and candidate != root:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Static resource does not exist.",
                HTTPStatus.NOT_FOUND,
            )
        if not candidate.is_file():
            candidate = root / "index.html"
        if not candidate.is_file():
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Static frontend is unavailable.",
                HTTPStatus.NOT_FOUND,
            )
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0]
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            content_type or "application/octet-stream",
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            return

    def _handle_get(
        self,
        parts: tuple[str, ...],
    ) -> tuple[HTTPStatus, object]:
        if parts == ("api", "health"):
            runtime = (
                self.server.provider_runtime.to_public_dict()
                if self.server.provider_runtime is not None
                else {"provider": None, "model": None}
            )
            return HTTPStatus.OK, {
                "service": "alphanoah-a1-edge-agent",
                "status": "ok",
                "database": "ok",
                "provider": runtime.get("provider"),
                "model": runtime.get("model"),
            }
        if (
            parts == ("api", "runtime")
            and self.server.provider_runtime is not None
        ):
            return (
                HTTPStatus.OK,
                self.server.provider_runtime.to_public_dict(),
            )
        if (
            parts == ("api", "workspace")
            and self.server.projection_adapter is not None
        ):
            return (
                HTTPStatus.OK,
                self.server.projection_adapter.get_workspace(),
            )
        if (
            parts == ("api", "events")
            and self.server.projection_adapter is not None
        ):
            return (
                HTTPStatus.OK,
                self.server.projection_adapter.get_events(),
            )
        if (
            parts == ("api", "digital-employees")
            and self.server.projection_adapter is not None
        ):
            return (
                HTTPStatus.OK,
                self.server.projection_adapter.get_digital_employees(),
            )
        if (
            parts == ("api", "pulse")
            and self.server.projection_adapter is not None
        ):
            return (
                HTTPStatus.OK,
                self.server.projection_adapter.get_pulse(),
            )
        if (
            len(parts) == 4
            and parts[:3] == ("api", "demo", "events")
            and self.server.demo_adapter is not None
        ):
            return (
                HTTPStatus.OK,
                self.server.demo_adapter.get_event(parts[3]),
            )
        if len(parts) == 3 and parts[:2] == ("api", "events"):
            return HTTPStatus.OK, self.server.adapter.get_event(parts[2])
        if (
            len(parts) == 4
            and parts[:2] == ("api", "events")
            and parts[3] == "analysis"
        ):
            return (
                HTTPStatus.OK,
                self.server.adapter.get_analysis(parts[2]),
            )
        if (
            len(parts) == 4
            and parts[:2] == ("api", "events")
            and parts[3] == "task"
        ):
            return HTTPStatus.OK, self.server.adapter.get_task(parts[2])
        if (
            len(parts) == 4
            and parts[:2] == ("api", "events")
            and parts[3] == "timeline"
        ):
            return (
                HTTPStatus.OK,
                self.server.adapter.get_timeline(parts[2]),
            )
        raise WebAdapterError(
            WebErrorCode.INVALID_REQUEST,
            "API endpoint does not exist.",
            HTTPStatus.NOT_FOUND,
        )

    def _handle_post(
        self,
        parts: tuple[str, ...],
        payload: object,
    ) -> tuple[HTTPStatus, object]:
        if (
            parts == ("api", "demo", "events")
            and self.server.demo_adapter is not None
        ):
            if (
                self.server.provider_runtime is not None
                and not self.server.provider_runtime.ready
            ):
                raise WebAdapterError(
                    WebErrorCode.PROVIDER_UNAVAILABLE,
                    "AI provider runtime is unavailable.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return (
                HTTPStatus.CREATED,
                self.server.demo_adapter.create_event(payload),
            )
        if parts == ("api", "events"):
            return (
                HTTPStatus.CREATED,
                self.server.adapter.create_event(payload),
            )
        if (
            len(parts) == 4
            and parts[:2] == ("api", "events")
            and parts[3] == "analysis"
        ):
            if (
                self.server.provider_runtime is not None
                and not self.server.provider_runtime.ready
            ):
                raise WebAdapterError(
                    WebErrorCode.PROVIDER_UNAVAILABLE,
                    "AI provider runtime is unavailable.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return HTTPStatus.OK, self.server.adapter.analyze_event(
                parts[2], payload
            )
        if (
            len(parts) == 4
            and parts[:2] == ("api", "events")
            and parts[3] == "review"
        ):
            return (
                HTTPStatus.OK,
                self.server.adapter.submit_review(parts[2], payload),
            )
        if (
            len(parts) == 4
            and parts[:2] == ("api", "events")
            and parts[3] == "task"
        ):
            return (
                HTTPStatus.OK,
                self.server.adapter.create_task(parts[2], payload),
            )
        if (
            len(parts) == 4
            and parts[:2] == ("api", "tasks")
            and parts[3] == "evidence"
        ):
            return (
                HTTPStatus.CREATED,
                self.server.adapter.submit_evidence(parts[2], payload),
            )
        if (
            len(parts) == 4
            and parts[:2] == ("api", "tasks")
            and parts[3] == "start"
        ):
            return HTTPStatus.OK, self.server.adapter.start_task(
                parts[2], payload
            )
        if (
            len(parts) == 5
            and parts[:2] == ("api", "tasks")
            and parts[3:] == ("review", "begin")
        ):
            return HTTPStatus.OK, self.server.adapter.begin_final_review(
                parts[2], payload
            )
        if (
            len(parts) == 4
            and parts[:2] == ("api", "tasks")
            and parts[3] == "review"
        ):
            return HTTPStatus.OK, self.server.adapter.submit_final_review(
                parts[2], payload
            )
        raise WebAdapterError(
            WebErrorCode.INVALID_REQUEST,
            "API endpoint does not exist.",
            HTTPStatus.NOT_FOUND,
        )

    def _read_json_body(self) -> object:
        if self.headers.get_all("Transfer-Encoding", []):
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Transfer-Encoding is not supported.",
                HTTPStatus.BAD_REQUEST,
            )
        content_type_headers = self.headers.get_all("Content-Type", [])
        if len(content_type_headers) != 1:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Content-Type must be supplied exactly once.",
                HTTPStatus.BAD_REQUEST,
            )
        if (
            self.headers.get_content_type() != "application/json"
            or self.headers.get_content_charset() not in (None, "utf-8")
        ):
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Request body must be UTF-8 application/json.",
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            )
        length_headers = self.headers.get_all("Content-Length", [])
        if len(length_headers) != 1:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Content-Length must be supplied exactly once.",
                HTTPStatus.LENGTH_REQUIRED,
            )
        raw_length = length_headers[0]
        if (
            not raw_length.isascii()
            or not raw_length.isdecimal()
            or len(raw_length) > 20
        ):
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Content-Length is invalid.",
                HTTPStatus.BAD_REQUEST,
            )
        length = int(raw_length)
        if length > MAX_REQUEST_BODY_BYTES:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Request body exceeds the configured size limit.",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        try:
            body = self.rfile.read(length)
        except (OSError, TimeoutError) as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Request body could not be read.",
                HTTPStatus.BAD_REQUEST,
            ) from exc
        if len(body) != length:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Request body was incomplete.",
                HTTPStatus.BAD_REQUEST,
            )
        try:
            return json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as exc:
            raise WebAdapterError(
                WebErrorCode.INVALID_REQUEST,
                "Request body is not valid JSON.",
                HTTPStatus.BAD_REQUEST,
            ) from exc

    def _method_not_allowed(self) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {
                "error_code": WebErrorCode.INVALID_REQUEST.value,
                "message": "HTTP method is not supported.",
            },
            extra_headers={"Allow": "GET, POST"},
            include_body=self.command != "HEAD",
        )

    def _send_json(
        self,
        status: HTTPStatus,
        payload: object,
        *,
        extra_headers: dict[str, str] | None = None,
        include_body: bool = True,
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if include_body:
            try:
                self.wfile.write(body)
            except OSError:
                return


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def create_server(
    database_path: str | Path,
    *,
    port: int = DEFAULT_PORT,
    application: RestaurantAirconGoldenPath | None = None,
    config_path: str | Path = DEFAULT_AI_RUNTIME_CONFIG,
    startup_options: StartupProviderOptions | None = None,
    orchestrator: ProviderRuntimeOrchestrator | None = None,
    provider_runtime: ResolvedProviderRuntime | None = None,
    discovery_timeout_seconds: float = 2.0,
    static_directory: str | Path | None = None,
) -> WebAdapterHTTPServer:
    """Compose Web from one resolved or explicitly injected Provider."""

    if not 0 <= port <= 65_535:
        raise ValueError("port must be between 0 and 65535")
    resolved = provider_runtime
    if application is None:
        if resolved is None:
            resolver = orchestrator or ProviderRuntimeOrchestrator(
                discovery_timeout_seconds=discovery_timeout_seconds,
            )
            resolved = resolver.resolve(
                config_path,
                options=startup_options,
            )
        raw_provider = (
            resolved.provider_instance
            if resolved.provider_instance is not None
            else UnavailableAnalysisProvider()
        )
        selected_application = build_restaurant_aircon_golden_path(
            database_path,
            raw_provider=raw_provider,
        )
    else:
        selected_application = application
        reliable_provider = getattr(
            selected_application,
            "provider",
            None,
        )
        raw_provider = getattr(
            reliable_provider,
            "provider",
            reliable_provider,
        )
        if resolved is not None:
            if raw_provider is not resolved.provider_instance:
                raise ValueError(
                    "application Provider and provider_runtime must match"
                )
        else:
            resolved = ResolvedProviderRuntime.injected(raw_provider)
    demo_application = build_demo_activation_application(
        selected_application
    )
    return WebAdapterHTTPServer(
        (LOCAL_HOST, port),
        RestaurantAirconWebAdapter(selected_application),
        DemoActivationWebAdapter(demo_application),
        projection_adapter=RuntimeProjectionWebAdapter(
            selected_application,
            responsibility_directory=(
                demo_application.responsibility_directory
            ),
        ),
        provider_runtime=resolved,
        static_directory=static_directory,
    )


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError(
            "port must be between 1 and 65535"
        )
    return port


def _provider_kind(value: str) -> ProviderKind:
    try:
        return ProviderKind(value.replace("-", "_"))
    except ValueError as exc:
        supported = ", ".join(
            item.value.replace("_", "-") for item in ProviderKind
        )
        raise argparse.ArgumentTypeError(
            f"provider must be one of: {supported}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local-only AlphaNoah Task 05C-1 JSON API adapter."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT)
    parser.add_argument("--static-dir", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_AI_RUNTIME_CONFIG,
        help="Secret-free AI Runtime configuration file.",
    )
    parser.add_argument(
        "--provider",
        type=_provider_kind,
        help="Explicit Provider selection; discovery never selects for you.",
    )
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--model-digest")
    parser.add_argument(
        "--credential-env",
        help="Environment variable name containing the Provider credential.",
    )
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=2.0,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    server = create_server(
        args.db,
        port=args.port,
        config_path=args.config,
        startup_options=StartupProviderOptions(
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            model_digest=args.model_digest,
            credential_env=args.credential_env,
        ),
        discovery_timeout_seconds=args.discovery_timeout,
        static_directory=args.static_dir,
    )
    actual_port = server.server_address[1]
    print("AlphaNoah Task 05C-1 Web Adapter")
    print(f"Listening on http://{LOCAL_HOST}:{actual_port}/api")
    runtime_status = server.provider_runtime.to_public_dict()
    print(
        "Provider runtime: "
        f"{runtime_status['status']}; "
        f"provider={runtime_status['provider']}; "
        f"selection={runtime_status['selection_source']}"
    )
    print("Localhost only. No authentication.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Stopping AlphaNoah Web Adapter.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
