from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.paths import factory_artifact_path
from agent_factory.tooling.providers.mcp import MCPServerConfig, MCPServersConfig
from agent_factory.tooling.providers.skill import EnabledSkillConfig, EnabledSkillsConfig
from agent_factory.tooling.skills import parse_skill_directory


EXTENSION_REGISTRY_ROOT_ENV = "AGENTFACTORY_EXTENSION_REGISTRY_ROOT"
EXTENSION_BINDINGS_FILENAME = "extension_bindings.json"
MCP_TOOL_CATALOG_FILENAME = "mcp_tool_catalog.json"
BINDING_COLLECTION_DIRS = (
    "agent_runtime",
    "create_agent_workspaces",
    "factory",
    "packages",
)

ExtensionKind = Literal["mcp", "skill"]

_registry_lock = threading.RLock()


class AgentExtensionBindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "agent_extension_bindings.v0"
    mcp_server_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)

    def identifiers(self, kind: ExtensionKind) -> list[str]:
        return self.mcp_server_ids if kind == "mcp" else self.skill_ids


class RegisteredMCPTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    name: str
    description: str = ""
    risk_level: str = "medium"
    permission_scope: str = "extension"
    permission_tags: list[str] = Field(default_factory=list)
    concurrent: bool = False


class MCPToolCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "mcp_tool_catalog.v1"
    servers: dict[str, list[RegisteredMCPTool]] = Field(default_factory=dict)


def default_extension_registry_root() -> Path:
    configured = os.getenv(EXTENSION_REGISTRY_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return factory_artifact_path("extension_registry").resolve()


def registry_mcp_path() -> Path:
    return default_extension_registry_root() / "mcp_servers.json"


def registry_skills_path() -> Path:
    return default_extension_registry_root() / "enabled_skills.json"


def registry_mcp_tool_catalog_path() -> Path:
    return default_extension_registry_root() / MCP_TOOL_CATALOG_FILENAME


def registry_skill_content_root() -> Path:
    return default_extension_registry_root() / "skills"


def load_registered_mcp_servers() -> MCPServersConfig:
    config = MCPServersConfig.model_validate(_read_json(registry_mcp_path()))
    return MCPServersConfig(
        servers=[server.model_copy(update={"enabled": True}) for server in config.servers]
    )


def load_registered_mcp_tool_catalog() -> MCPToolCatalog:
    return MCPToolCatalog.model_validate(_read_json(registry_mcp_tool_catalog_path()))


def replace_registered_mcp_tool_catalog(server_id: str, tools: list[dict[str, Any]]) -> None:
    identifier = str(server_id or "").strip()
    if not identifier:
        raise ValueError("MCP catalog server_id is required")
    with _registry_lock:
        catalog = load_registered_mcp_tool_catalog()
        next_servers = dict(catalog.servers)
        next_servers[identifier] = [RegisteredMCPTool.model_validate(tool) for tool in tools]
        updated = MCPToolCatalog(servers=next_servers)
        _write_json(registry_mcp_tool_catalog_path(), updated.model_dump(mode="json"))


def remove_registered_mcp_tool_catalog(server_id: str) -> None:
    identifier = str(server_id or "").strip()
    with _registry_lock:
        catalog = load_registered_mcp_tool_catalog()
        if identifier not in catalog.servers:
            return
        next_servers = dict(catalog.servers)
        next_servers.pop(identifier, None)
        _write_json(
            registry_mcp_tool_catalog_path(),
            MCPToolCatalog(servers=next_servers).model_dump(mode="json"),
        )


def save_registered_mcp_servers(config: MCPServersConfig) -> None:
    normalized = MCPServersConfig(
        servers=sorted(
            (
                server.model_copy(update={"enabled": True})
                for server in config.servers
            ),
            key=lambda server: server.server_id,
        )
    )
    _write_json(registry_mcp_path(), normalized.model_dump(mode="json"))


def load_registered_skills() -> EnabledSkillsConfig:
    config = EnabledSkillsConfig.model_validate(_read_json(registry_skills_path()))
    return EnabledSkillsConfig(
        skills=[skill.model_copy(update={"enabled": True}) for skill in config.skills]
    )


def load_resolved_registered_skills() -> EnabledSkillsConfig:
    config = load_registered_skills()
    return EnabledSkillsConfig(
        skills=[_normalized_registered_skill(skill) for skill in config.skills]
    )


def save_registered_skills(config: EnabledSkillsConfig) -> None:
    normalized = EnabledSkillsConfig(
        skills=sorted(
            (skill.model_copy(update={"enabled": True}) for skill in config.skills),
            key=lambda skill: skill.skill_id,
        )
    )
    _write_json(registry_skills_path(), normalized.model_dump(mode="json"))


def find_registered_mcp_server(server_id: str) -> MCPServerConfig | None:
    identifier = str(server_id or "").strip()
    return next(
        (
            server
            for server in load_registered_mcp_servers().servers
            if server.server_id == identifier
        ),
        None,
    )


def find_registered_skill(skill_id: str) -> EnabledSkillConfig | None:
    identifier = str(skill_id or "").strip()
    return next(
        (
            skill
            for skill in load_registered_skills().skills
            if skill.skill_id == identifier
        ),
        None,
    )


def upsert_registered_mcp_servers(
    servers: list[MCPServerConfig],
) -> MCPServersConfig:
    replacements = {server.server_id: server for server in servers}
    current = load_registered_mcp_servers()
    updated = MCPServersConfig(
        servers=[
            *(
                server
                for server in current.servers
                if server.server_id not in replacements
            ),
            *replacements.values(),
        ]
    )
    save_registered_mcp_servers(updated)
    return updated


def upsert_registered_skill(skill: EnabledSkillConfig) -> EnabledSkillsConfig:
    current = load_registered_skills()
    updated = EnabledSkillsConfig(
        skills=[
            *(
                item
                for item in current.skills
                if item.skill_id != skill.skill_id
            ),
            skill,
        ]
    )
    save_registered_skills(updated)
    return updated


def import_registered_skill_directory(
    source: str | Path,
    *,
    enabled: bool = True,
    required: bool = False,
    source_kind: str = "local",
    replace_skill_id: str | None = None,
    expected_skill_id: str | None = None,
) -> EnabledSkillConfig:
    source_root = Path(source).expanduser().resolve()
    _assert_skill_tree_safe(source_root)
    relaxed = source_kind in {"skillhub", "distribution"}
    package = parse_skill_directory(
        source_root,
        allow_directory_name_mismatch=relaxed,
        allow_missing_frontmatter=relaxed,
        fallback_name=expected_skill_id or source_root.name,
    )
    skill_id = package.name
    if expected_skill_id and skill_id != expected_skill_id:
        raise ValueError(
            f"Skill identity does not match the registry entry: "
            f"{expected_skill_id} != {skill_id}"
        )
    content_root = registry_skill_content_root()
    destination = (content_root / skill_id).resolve()
    _require_managed_skill_path(destination)
    replacement_id = str(replace_skill_id or "").strip()
    if replacement_id and replacement_id != skill_id:
        raise ValueError(
            "Editing a registered Skill cannot change its identity; add the new "
            "Skill separately"
        )

    content_root.mkdir(parents=True, exist_ok=True)
    transaction_root = content_root / f".import-{uuid4().hex}"
    staged = transaction_root / skill_id
    backup = transaction_root / "previous"
    transaction_root.mkdir(parents=True)
    previous_config = load_registered_skills()
    config_saved = False
    destination_installed = False
    try:
        shutil.copytree(
            source_root,
            staged,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
        )
        parse_skill_directory(
            staged,
            allow_directory_name_mismatch=relaxed,
            allow_missing_frontmatter=relaxed,
            fallback_name=skill_id,
        )
        if destination.exists():
            destination.rename(backup)
        staged.rename(destination)
        destination_installed = True
        skill = EnabledSkillConfig(
            skill_id=skill_id,
            enabled=enabled,
            source=source_kind,
            path=(Path("skills") / skill_id).as_posix(),
            required=required,
        )
        removed_ids = {skill_id}
        if replacement_id:
            removed_ids.add(replacement_id)
        save_registered_skills(
            EnabledSkillsConfig(
                skills=[
                    *(
                        item
                        for item in previous_config.skills
                        if item.skill_id not in removed_ids
                    ),
                    skill,
                ]
            )
        )
        config_saved = True
        if backup.exists():
            shutil.rmtree(backup)
        return skill
    except Exception:
        if config_saved:
            save_registered_skills(previous_config)
        if destination_installed and destination.exists():
            shutil.rmtree(destination)
        if backup.exists():
            backup.rename(destination)
        raise
    finally:
        shutil.rmtree(transaction_root, ignore_errors=True)


def remove_registered_extension(kind: ExtensionKind, identifier: str) -> bool:
    target = str(identifier or "").strip()
    if kind == "mcp":
        current = load_registered_mcp_servers()
        retained = [
            server for server in current.servers if server.server_id != target
        ]
        removed = len(retained) != len(current.servers)
        if removed:
            save_registered_mcp_servers(MCPServersConfig(servers=retained))
            remove_registered_mcp_tool_catalog(target)
            remove_extension_from_all_bindings("mcp", target)
        return removed
    current_skills = load_registered_skills()
    retained_skills = [
        skill for skill in current_skills.skills if skill.skill_id != target
    ]
    removed = len(retained_skills) != len(current_skills.skills)
    if removed:
        save_registered_skills(EnabledSkillsConfig(skills=retained_skills))
        remove_extension_from_all_bindings("skill", target)
        _remove_registered_skill_content(
            next(
                (skill for skill in current_skills.skills if skill.skill_id == target),
                None,
            )
        )
    return removed


def remove_extension_from_all_bindings(
    kind: ExtensionKind,
    identifier: str,
) -> list[Path]:
    target = str(identifier or "").strip()
    if not target:
        return []
    changed: list[Path] = []
    artifact_root = factory_artifact_path().resolve()
    if not artifact_root.is_dir():
        return changed
    candidates = (
        path
        for collection in BINDING_COLLECTION_DIRS
        for path in (artifact_root / collection).rglob(EXTENSION_BINDINGS_FILENAME)
        if not any(part.startswith(".") for part in path.relative_to(artifact_root).parts)
    )
    for path in sorted(candidates):
        payload = _read_json(path)
        if not payload:
            continue
        bindings = AgentExtensionBindings.model_validate(payload)
        values = bindings.identifiers(kind)
        retained = [value for value in values if value != target]
        if retained == values:
            continue
        updated = bindings.model_copy(
            update={
                "mcp_server_ids" if kind == "mcp" else "skill_ids": retained
            }
        )
        save_agent_extension_bindings(path.parent, updated)
        changed.append(path)
    return changed


def bindings_path(extension_root: str | Path) -> Path:
    return Path(extension_root).expanduser().resolve() / EXTENSION_BINDINGS_FILENAME


def load_agent_extension_bindings(
    extension_roots: list[str | Path] | tuple[str | Path, ...],
) -> AgentExtensionBindings:
    resolved = AgentExtensionBindings()
    for root in extension_roots:
        payload = _read_json(bindings_path(root))
        if not payload:
            continue
        resolved = AgentExtensionBindings.model_validate(payload)
    return AgentExtensionBindings(
        mcp_server_ids=_stable_identifiers(resolved.mcp_server_ids),
        skill_ids=_stable_identifiers(resolved.skill_ids),
    )


def save_agent_extension_bindings(
    extension_root: str | Path,
    bindings: AgentExtensionBindings,
) -> None:
    normalized = AgentExtensionBindings(
        mcp_server_ids=_stable_identifiers(bindings.mcp_server_ids),
        skill_ids=_stable_identifiers(bindings.skill_ids),
    )
    _write_json(bindings_path(extension_root), normalized.model_dump(mode="json"))


def set_agent_extension_binding(
    extension_root: str | Path,
    *,
    kind: ExtensionKind,
    identifier: str,
    enabled: bool,
    inherited_extension_roots: list[str | Path] | tuple[str | Path, ...] = (),
) -> AgentExtensionBindings:
    target = str(identifier or "").strip()
    if not target:
        raise ValueError("extension identifier is required")
    if enabled and kind == "mcp" and find_registered_mcp_server(target) is None:
        raise ValueError(f"MCP server is not registered: {target}")
    if enabled and kind == "skill" and find_registered_skill(target) is None:
        raise ValueError(f"Skill is not registered: {target}")
    current = registered_agent_extension_bindings(
        [*inherited_extension_roots, extension_root]
    )
    identifiers = set(current.identifiers(kind))
    if enabled:
        identifiers.add(target)
    else:
        identifiers.discard(target)
    updated = current.model_copy(
        update={
            "mcp_server_ids" if kind == "mcp" else "skill_ids": sorted(identifiers)
        }
    )
    save_agent_extension_bindings(extension_root, updated)
    return updated


def selected_registry_configs(
    extension_roots: list[str | Path] | tuple[str | Path, ...],
) -> tuple[MCPServersConfig, EnabledSkillsConfig, AgentExtensionBindings]:
    bindings = load_agent_extension_bindings(extension_roots)
    selected_mcp_ids = set(bindings.mcp_server_ids)
    selected_skill_ids = set(bindings.skill_ids)
    mcp = load_registered_mcp_servers()
    skills = load_registered_skills()
    resolved_bindings = AgentExtensionBindings(
        mcp_server_ids=[
            server.server_id
            for server in mcp.servers
            if server.server_id in selected_mcp_ids
        ],
        skill_ids=[
            skill.skill_id
            for skill in skills.skills
            if skill.skill_id in selected_skill_ids
        ],
    )
    return (
        MCPServersConfig(
            servers=[
                server
                for server in mcp.servers
                if server.server_id in selected_mcp_ids
            ]
        ),
        EnabledSkillsConfig(
            skills=[
                _normalized_registered_skill(skill)
                for skill in skills.skills
                if skill.skill_id in selected_skill_ids
            ]
        ),
        resolved_bindings,
    )


def registered_agent_extension_bindings(
    extension_roots: list[str | Path] | tuple[str | Path, ...],
) -> AgentExtensionBindings:
    bindings = load_agent_extension_bindings(extension_roots)
    registered_mcp_ids = {
        server.server_id for server in load_registered_mcp_servers().servers
    }
    registered_skill_ids = {
        skill.skill_id for skill in load_registered_skills().skills
    }
    return AgentExtensionBindings(
        mcp_server_ids=[
            identifier
            for identifier in bindings.mcp_server_ids
            if identifier in registered_mcp_ids
        ],
        skill_ids=[
            identifier
            for identifier in bindings.skill_ids
            if identifier in registered_skill_ids
        ],
    )


def _stable_identifiers(values: list[str]) -> list[str]:
    return sorted(
        {
            identifier
            for value in values
            if (identifier := str(value or "").strip())
        }
    )


def _normalized_registered_skill(skill: EnabledSkillConfig) -> EnabledSkillConfig:
    path = Path(skill.path).expanduser()
    if path.is_absolute():
        return skill
    return skill.model_copy(
        update={"path": str((default_extension_registry_root() / path).resolve())}
    )


def _remove_registered_skill_content(skill: EnabledSkillConfig | None) -> None:
    path = _registered_skill_content_path(skill)
    if path is None:
        return
    if not _is_managed_skill_path(path):
        return
    if path.exists():
        shutil.rmtree(path)


def _registered_skill_content_path(skill: EnabledSkillConfig | None) -> Path | None:
    if skill is None:
        return None
    configured = Path(skill.path).expanduser()
    return (
        configured.resolve()
        if configured.is_absolute()
        else (default_extension_registry_root() / configured).resolve()
    )


def _assert_skill_tree_safe(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Skill directories cannot contain symbolic links: {path}")


def _is_managed_skill_path(path: Path) -> bool:
    root = registry_skill_content_root().resolve()
    target = path.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return target != root


def _require_managed_skill_path(path: Path) -> None:
    if not _is_managed_skill_path(path):
        raise ValueError(f"Skill path is outside the managed registry: {path}")


def _read_json(path: Path) -> dict:
    with _registry_lock:
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"extension registry file must contain an object: {path}")
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    with _registry_lock:
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            temporary_path.replace(path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
