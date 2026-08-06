from __future__ import annotations

from pathlib import Path

from agent_factory.paths import factory_artifact_path
from agent_factory.tooling.extension_registry import (
    bindings_path,
    set_agent_extension_binding,
    upsert_registered_mcp_servers,
)
from agent_factory.tooling.factory_extensions import (
    default_builtin_factory_extension_root,
    default_system_agent_extension_root,
)
from agent_factory.tooling.providers.mcp import MCPServerConfig


BUILTIN_WEB_SEARCH_SERVER_ID = "web_search"
BUILTIN_TAVILY_API_KEY = "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"


def ensure_builtin_web_search_mcp() -> MCPServerConfig:
    mcp_root = factory_artifact_path("mcp", "web_search").resolve()
    entrypoint = mcp_root / "dist" / "index.js"
    _require_built_web_search_mcp(entrypoint)
    server = MCPServerConfig(
        server_id=BUILTIN_WEB_SEARCH_SERVER_ID,
        transport="stdio",
        command="node",
        args=[str(entrypoint)],
        cwd=str(mcp_root),
        env={
            "TAVILY_API_KEY": BUILTIN_TAVILY_API_KEY,
            "DEFAULT_SEARCH_ENGINE": "tavily",
        },
        source={
            "kind": "builtin",
            "name": "Tavily Web Search",
            "description": "Built-in Tavily MCP for the Hackson test deployment.",
        },
        enabled=True,
        required=False,
        concurrent_default=True,
        timeout_seconds=120,
    )
    upsert_registered_mcp_servers([server])
    for extension_root in _builtin_agent_extension_roots():
        _ensure_default_mcp_binding(extension_root, server.server_id)
    return server


def _builtin_agent_extension_roots() -> tuple[Path, ...]:
    return (
        default_system_agent_extension_root("factory_chat"),
        default_builtin_factory_extension_root(),
    )


def _ensure_default_mcp_binding(extension_root: Path, server_id: str) -> None:
    if bindings_path(extension_root).is_file():
        return
    set_agent_extension_binding(
        extension_root,
        kind="mcp",
        identifier=server_id,
        enabled=True,
    )


def _require_built_web_search_mcp(entrypoint: Path) -> None:
    if not entrypoint.is_file():
        raise FileNotFoundError(
            f"built-in web search MCP entrypoint is unavailable: {entrypoint}"
        )
