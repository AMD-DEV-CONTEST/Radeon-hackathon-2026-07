from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.paths import project_root
from agent_factory.runtime_kernel.extensions.schema import (
    AgentInstanceExtensionConfigBundle,
    AgentInstanceExtensionSources,
)
from agent_factory.tooling.extension_registry import (
    default_extension_registry_root,
    registry_mcp_path,
    registry_skills_path,
    selected_registry_configs,
)


class AgentInstanceExtensionConfigLoader:
    def __init__(
        self,
        extension_root: str | Path,
        *,
        inherited_extension_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    ) -> None:
        self.extension_root = Path(extension_root).expanduser().resolve()
        self.inherited_extension_roots = _unique_paths(
            Path(root).expanduser().resolve()
            for root in (inherited_extension_roots or [])
        )

    def load(self) -> AgentInstanceExtensionConfigBundle:
        roots = _unique_paths([*self.inherited_extension_roots, self.extension_root])
        mcp_config, skills_config, _bindings = selected_registry_configs(roots)
        registry_root = default_extension_registry_root()
        mcp_path = registry_mcp_path()
        skills_path = registry_skills_path()
        return AgentInstanceExtensionConfigBundle(
            sources=AgentInstanceExtensionSources(
                extension_root=self.extension_root,
                extension_roots=[*roots, registry_root],
                mcp_servers_path=mcp_path if mcp_path.is_file() else None,
                mcp_servers_paths=[mcp_path] if mcp_path.is_file() else [],
                enabled_skills_path=skills_path if skills_path.is_file() else None,
                enabled_skills_paths=[skills_path] if skills_path.is_file() else [],
            ),
            mcp_servers=mcp_config,
            enabled_skills=skills_config,
        )


def default_builtin_agent_extension_root() -> Path:
    return project_root() / "SystemPackage" / "extensions"


def _unique_paths(paths: Any) -> list[Path]:
    items: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if resolved in seen:
            continue
        items.append(resolved)
        seen.add(resolved)
    return items
