from __future__ import annotations

from typing import Any, Mapping, Protocol

from agent_factory.tooling.entrypoints.base import EntrypointAdapterError, ToolEntrypointCallable, parse_protocol
from agent_factory.tooling.envelope import tool_envelope


class MCPToolClient(Protocol):
    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | Any:
        ...


class MCPEntrypointAdapter:
    protocol = "mcp"

    def __init__(self, *, clients: Mapping[str, MCPToolClient] | None = None) -> None:
        self._clients = dict(clients or {})

    def can_load(self, entrypoint: str) -> bool:
        return parse_protocol(entrypoint).protocol == "mcp"

    def load(self, entrypoint: str) -> ToolEntrypointCallable:
        parsed = parse_protocol(entrypoint)
        server_id, tool_name = _split_mcp_target(parsed.target)
        client = self._clients.get(server_id)
        if client is None:
            raise EntrypointAdapterError(f"MCP client is not configured for server: {server_id}")

        def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
            result = client.call_tool(tool_name, arguments)
            return tool_envelope(_normalize_mcp_result(result))

        return run


def _split_mcp_target(target: str) -> tuple[str, str]:
    if "/" not in target:
        raise EntrypointAdapterError("MCP entrypoint must use 'mcp:<server_id>/<tool_name>'")
    server_id, tool_name = target.split("/", 1)
    server_id = server_id.strip()
    tool_name = tool_name.strip()
    if not server_id or not tool_name:
        raise EntrypointAdapterError("MCP server_id and tool_name must be non-empty")
    return server_id, tool_name


def _normalize_mcp_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        dumped = result.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {"result": dumped}
    if hasattr(result, "dict"):
        dumped = result.dict()
        return dumped if isinstance(dumped, dict) else {"result": dumped}
    return {"result": result}
