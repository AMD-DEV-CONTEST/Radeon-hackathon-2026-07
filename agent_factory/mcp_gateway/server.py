from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent_factory.mcp_gateway.protocol import (
    MCPGatewayCallToolRequest,
    MCPGatewayCallToolResponse,
    MCPGatewayError,
    MCPGatewayHealthResponse,
    MCPGatewayListToolsResponse,
    MCPGatewayServersResponse,
    MCPGatewayToolDescriptor,
)
from agent_factory.tooling.mcp_runtime import MCPRuntimeManager
from agent_factory.tooling.providers.mcp import MCPDiscoveredTool, MCPServersConfig


@dataclass(frozen=True, slots=True)
class MCPGatewayEndpoint:
    host: str
    port: int

    @property
    def host_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def local_url(self) -> str:
        return self.host_url


class MCPGatewayServer:
    def __init__(self, *, config: MCPServersConfig, host: str = "127.0.0.1", port: int = 0) -> None:
        self.config = config
        self.runtime_manager = MCPRuntimeManager(config)
        self._httpd = ThreadingHTTPServer((host, port), _handler_factory(self.runtime_manager))
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> MCPGatewayEndpoint:
        host, port = self._httpd.server_address[:2]
        return MCPGatewayEndpoint(host=str(host), port=int(port))

    def start(self) -> MCPGatewayEndpoint:
        if self._thread is not None:
            return self.endpoint
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name=f"agentfactory-mcp-gateway-{self.endpoint.port}",
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


def _handler_factory(runtime_manager: MCPRuntimeManager) -> type[BaseHTTPRequestHandler]:
    class MCPGatewayRequestHandler(BaseHTTPRequestHandler):
        server_version = "AgentFactoryMCPGateway/0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                clients = runtime_manager.clients()
                self._write_json(
                    HTTPStatus.OK,
                    MCPGatewayHealthResponse(server_count=len(clients)).model_dump(mode="json"),
                )
                return
            if parsed.path == "/servers":
                self._write_json(
                    HTTPStatus.OK,
                    MCPGatewayServersResponse(servers=sorted(runtime_manager.clients())).model_dump(mode="json"),
                )
                return
            if parsed.path == "/tools":
                server_id = _first_query_value(parsed.query, "server_id")
                if not server_id:
                    self._write_gateway_error(
                        HTTPStatus.BAD_REQUEST,
                        where="mcp_gateway.tools",
                        message="server_id query parameter is required",
                    )
                    return
                self._handle_list_tools(server_id)
                return
            self._write_gateway_error(
                HTTPStatus.NOT_FOUND,
                where="mcp_gateway.route",
                message=f"unknown endpoint: {parsed.path}",
            )

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/call":
                self._write_gateway_error(
                    HTTPStatus.NOT_FOUND,
                    where="mcp_gateway.route",
                    message=f"unknown endpoint: {parsed.path}",
                )
                return
            try:
                request = MCPGatewayCallToolRequest.model_validate(self._read_json_body())
            except Exception as exc:
                self._write_gateway_error(
                    HTTPStatus.BAD_REQUEST,
                    where="mcp_gateway.call.request",
                    message=f"{type(exc).__name__}: {exc}",
                )
                return
            client = runtime_manager.clients().get(request.server_id)
            if client is None:
                self._write_gateway_error(
                    HTTPStatus.NOT_FOUND,
                    where="mcp_gateway.call.server",
                    message=f"MCP server is not configured: {request.server_id}",
                )
                return
            try:
                result = client.call_tool(request.tool_name, request.arguments)
            except Exception as exc:
                self._write_gateway_error(
                    HTTPStatus.BAD_GATEWAY,
                    where="mcp_gateway.call.runtime",
                    message=f"{type(exc).__name__}: {exc}",
                )
                return
            self._write_json(
                HTTPStatus.OK,
                MCPGatewayCallToolResponse(
                    server_id=request.server_id,
                    tool_name=request.tool_name,
                    result=result if isinstance(result, dict) else {"result": result},
                ).model_dump(mode="json"),
            )

        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _handle_list_tools(self, server_id: str) -> None:
            client = runtime_manager.clients().get(server_id)
            if client is None:
                self._write_gateway_error(
                    HTTPStatus.NOT_FOUND,
                    where="mcp_gateway.tools.server",
                    message=f"MCP server is not configured: {server_id}",
                )
                return
            try:
                tools = [
                    MCPGatewayToolDescriptor.model_validate(
                        MCPDiscoveredTool.model_validate(tool).model_dump(mode="json")
                    )
                    for tool in client.list_tools()
                ]
            except Exception as exc:
                self._write_gateway_error(
                    HTTPStatus.BAD_GATEWAY,
                    where="mcp_gateway.tools.runtime",
                    message=f"{type(exc).__name__}: {exc}",
                )
                return
            self._write_json(
                HTTPStatus.OK,
                MCPGatewayListToolsResponse(server_id=server_id, tools=tools).model_dump(mode="json"),
            )

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
                {"error": MCPGatewayError(where=where, message=message).model_dump(mode="json")},
            )

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return MCPGatewayRequestHandler


def _first_query_value(query: str, key: str) -> str | None:
    values = parse_qs(query).get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None
