from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import os
from threading import Lock

from agent_factory.mcp_gateway.server import MCPGatewayEndpoint, MCPGatewayServer
from agent_factory.tooling.providers.mcp import MCPServersConfig


MCP_GATEWAY_BIND_HOST_ENV = "AGENTFACTORY_HOST_MCP_GATEWAY_BIND_HOST"
MCP_GATEWAY_PORT_ENV = "AGENTFACTORY_HOST_MCP_GATEWAY_PORT"
MCP_GATEWAY_URL_ENV = "AGENTFACTORY_MCP_GATEWAY_URL"


@dataclass(slots=True)
class MCPGatewayHandle:
    key: str
    server: MCPGatewayServer
    endpoint: MCPGatewayEndpoint

    @property
    def host_url(self) -> str:
        return self.endpoint.host_url

    @property
    def local_url(self) -> str:
        return self.endpoint.local_url

    def stop(self) -> None:
        self.server.stop()


class HostMCPGatewayManager:
    def __init__(self) -> None:
        self._handles: dict[str, MCPGatewayHandle] = {}
        self._references: dict[str, int] = {}
        self._lock = Lock()

    def ensure_gateway(self, config: MCPServersConfig) -> MCPGatewayHandle | None:
        enabled_servers = [server for server in config.servers if server.enabled]
        if not enabled_servers:
            return None
        key = _config_key(config)
        with self._lock:
            existing = self._handles.get(key)
            if existing is not None:
                self._references[key] = self._references.get(key, 0) + 1
                return existing
            server = MCPGatewayServer(
                config=config,
                host=os.getenv(MCP_GATEWAY_BIND_HOST_ENV, "127.0.0.1"),
                port=_configured_port(),
            )
            endpoint = server.start()
            handle = MCPGatewayHandle(key=key, server=server, endpoint=endpoint)
            self._handles[key] = handle
            self._references[key] = 1
            return handle

    def release_gateway(self, key: str) -> None:
        handle: MCPGatewayHandle | None = None
        with self._lock:
            references = self._references.get(key, 0)
            if references > 1:
                self._references[key] = references - 1
                return
            self._references.pop(key, None)
            handle = self._handles.pop(key, None)
        if handle is not None:
            handle.stop()

    def close_all(self) -> None:
        with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
            self._references.clear()
        for handle in handles:
            handle.stop()


def build_gateway_clients(config: MCPServersConfig, gateway_url: str) -> dict[str, object]:
    client_cls = importlib.import_module("agent_factory.mcp_gateway.client").MCPGatewayClient

    return {
        server.server_id: client_cls(
            base_url=gateway_url,
            server_id=server.server_id,
            timeout_seconds=server.timeout_seconds,
        )
        for server in config.servers
        if server.enabled
    }


def configured_local_gateway_url() -> str | None:
    value = os.getenv(MCP_GATEWAY_URL_ENV)
    return value.strip() if value and value.strip() else None


def _configured_port() -> int:
    value = os.getenv(MCP_GATEWAY_PORT_ENV)
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _config_key(config: MCPServersConfig) -> str:
    payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
