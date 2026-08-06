from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from threading import Lock

from agent_factory.skillhub_gateway.server import SkillHubGatewayEndpoint, SkillHubGatewayServer


SKILLHUB_GATEWAY_BIND_HOST_ENV = "AGENTFACTORY_HOST_SKILLHUB_GATEWAY_BIND_HOST"
SKILLHUB_GATEWAY_PORT_ENV = "AGENTFACTORY_HOST_SKILLHUB_GATEWAY_PORT"
SKILLHUB_GATEWAY_URL_ENV = "AGENTFACTORY_SKILLHUB_GATEWAY_URL"


@dataclass(slots=True)
class SkillHubGatewayHandle:
    key: str
    server: SkillHubGatewayServer
    endpoint: SkillHubGatewayEndpoint
    extension_root: Path

    @property
    def host_url(self) -> str:
        return self.endpoint.host_url

    @property
    def local_url(self) -> str:
        return self.endpoint.local_url

    def stop(self) -> None:
        self.server.stop()


class HostSkillHubGatewayManager:
    def __init__(self) -> None:
        self._handles: dict[str, SkillHubGatewayHandle] = {}
        self._lock = Lock()

    def ensure_gateway(self, extension_root: str | Path) -> SkillHubGatewayHandle:
        root = Path(extension_root).expanduser().resolve()
        key = _root_key(root)
        with self._lock:
            existing = self._handles.get(key)
            if existing is not None:
                return existing
            server = SkillHubGatewayServer(
                extension_root=root,
                host=os.getenv(SKILLHUB_GATEWAY_BIND_HOST_ENV, "127.0.0.1"),
                port=_configured_port(),
            )
            endpoint = server.start()
            handle = SkillHubGatewayHandle(key=key, server=server, endpoint=endpoint, extension_root=root)
            self._handles[key] = handle
            return handle

    def close_all(self) -> None:
        with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
        for handle in handles:
            handle.stop()


def configured_local_skillhub_gateway_url() -> str | None:
    value = os.getenv(SKILLHUB_GATEWAY_URL_ENV)
    return value.strip() if value and value.strip() else None


def _configured_port() -> int:
    value = os.getenv(SKILLHUB_GATEWAY_PORT_ENV)
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _root_key(root: Path) -> str:
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()
