from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from agent_factory.mcp_gateway.protocol import (
    MCPGatewayCallToolRequest,
    MCPGatewayCallToolResponse,
    MCPGatewayListToolsResponse,
)
from agent_factory.tooling.providers.mcp import MCPDiscoveredTool


class MCPGatewayClientError(RuntimeError):
    pass


class MCPGatewayClient:
    def __init__(self, *, base_url: str, server_id: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.server_id = server_id
        self.timeout_seconds = timeout_seconds

    def list_tools(self) -> list[MCPDiscoveredTool]:
        payload = self._request_json("GET", f"/tools?{urlencode({'server_id': self.server_id})}")
        response = MCPGatewayListToolsResponse.model_validate(payload)
        return [MCPDiscoveredTool.model_validate(tool.model_dump(mode="json")) for tool in response.tools]

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        request = MCPGatewayCallToolRequest(
            server_id=self.server_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        payload = self._request_json("POST", "/call", request.model_dump(mode="json"))
        response = MCPGatewayCallToolResponse.model_validate(payload)
        return response.result

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with _NO_PROXY_OPENER.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MCPGatewayClientError(f"MCP gateway returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise MCPGatewayClientError(f"MCP gateway is unreachable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise MCPGatewayClientError("MCP gateway request timed out") from exc
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MCPGatewayClientError(f"MCP gateway returned invalid JSON: {raw[:200]}") from exc
        if not isinstance(decoded, dict):
            raise MCPGatewayClientError("MCP gateway response must be a JSON object")
        return decoded


_NO_PROXY_OPENER = build_opener(ProxyHandler({}))
