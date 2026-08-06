from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import urlparse

from agent_factory.skillhub_gateway.protocol import (
    SkillHubGatewayError,
    SkillHubGatewayHealthResponse,
    SkillHubGatewayRunRequest,
    SkillHubGatewayRunResponse,
)
from agent_factory.tooling.skillhub.service import SkillHubService


@dataclass(frozen=True, slots=True)
class SkillHubGatewayEndpoint:
    host: str
    port: int

    @property
    def host_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def local_url(self) -> str:
        return self.host_url


class SkillHubGatewayServer:
    def __init__(
        self,
        *,
        extension_root: str | Path,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.extension_root = Path(extension_root).expanduser().resolve()
        service = SkillHubService(extension_root=self.extension_root)
        self._httpd = ThreadingHTTPServer((host, port), _handler_factory(service))
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> SkillHubGatewayEndpoint:
        host, port = self._httpd.server_address[:2]
        return SkillHubGatewayEndpoint(host=str(host), port=int(port))

    def start(self) -> SkillHubGatewayEndpoint:
        if self._thread is not None:
            return self.endpoint
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name=f"agentfactory-skillhub-gateway-{self.endpoint.port}",
            daemon=True,
        )
        self._thread.start()
        return self.endpoint

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None


def _handler_factory(service: SkillHubService) -> type[BaseHTTPRequestHandler]:
    lock = threading.Lock()

    class SkillHubGatewayRequestHandler(BaseHTTPRequestHandler):
        server_version = "AgentFactorySkillHUBGateway/0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._write_json(
                    HTTPStatus.OK,
                    SkillHubGatewayHealthResponse(extension_root=str(service.extension_root)).model_dump(mode="json"),
                )
                return
            self._write_gateway_error(
                HTTPStatus.NOT_FOUND,
                where="skillhub_gateway.route",
                message=f"unknown endpoint: {parsed.path}",
            )

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/run":
                self._write_gateway_error(
                    HTTPStatus.NOT_FOUND,
                    where="skillhub_gateway.route",
                    message=f"unknown endpoint: {parsed.path}",
                )
                return
            try:
                request = SkillHubGatewayRunRequest.model_validate(self._read_json_body())
            except Exception as exc:
                self._write_gateway_error(
                    HTTPStatus.BAD_REQUEST,
                    where="skillhub_gateway.run.request",
                    message=f"{type(exc).__name__}: {exc}",
                )
                return
            try:
                with lock:
                    result = service.run(request.model_dump(mode="json", exclude_none=True))
            except Exception as exc:
                self._write_gateway_error(
                    HTTPStatus.BAD_GATEWAY,
                    where="skillhub_gateway.run.service",
                    message=f"{type(exc).__name__}: {exc}",
                )
                return
            self._write_json(
                HTTPStatus.OK,
                SkillHubGatewayRunResponse(result=result).model_dump(mode="json"),
            )

        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def _write_gateway_error(self, status: HTTPStatus, *, where: str, message: str) -> None:
            self._write_json(
                status,
                {"error": SkillHubGatewayError(where=where, message=message).model_dump(mode="json")},
            )

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return SkillHubGatewayRequestHandler
