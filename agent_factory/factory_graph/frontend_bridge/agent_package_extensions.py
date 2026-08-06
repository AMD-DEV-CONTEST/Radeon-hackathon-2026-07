from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import shlex
import threading
from typing import Any, Callable
from urllib.parse import urlparse

from agent_factory.exception_details import exception_contains, exception_leaf_messages
from agent_factory.runtime_contracts import LoadedAgentPackage
from agent_factory.runtime_kernel.extensions.loader import (
    AgentInstanceExtensionConfigLoader,
    default_builtin_agent_extension_root,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_paths import (
    extension_root_for_package,
    host_runtime_root,
    is_system_package,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_utils import (
    humanize_identifier,
    read_json_object,
    write_json_object,
    write_json_objects_atomically,
)
from agent_factory.tooling.output_store import default_tool_output_policy
from agent_factory.tooling.approval_policy import ToolApprovalOverrideConfig, ToolApprovalPolicyConfig
from agent_factory.tooling.extension_registry import (
    default_extension_registry_root,
    find_registered_mcp_server,
    import_registered_skill_directory,
    load_registered_mcp_servers,
    load_registered_mcp_tool_catalog,
    load_resolved_registered_skills,
    load_registered_skills,
    registered_agent_extension_bindings,
    registry_mcp_path,
    registry_skills_path,
    remove_registered_extension,
    remove_registered_mcp_tool_catalog,
    replace_registered_mcp_tool_catalog,
    set_agent_extension_binding,
    upsert_registered_mcp_servers,
    upsert_registered_skill,
)
from agent_factory.tooling.factory_extensions import (
    SystemAgentExtensionOwner,
    default_builtin_factory_extension_root,
    default_system_agent_extension_root,
)
from agent_factory.tooling.mcp_runtime import (
    MCPRuntimeCancelled,
    MCPRuntimeManager,
    MCPRuntimeOperation,
)
from agent_factory.tooling.providers import (
    EnabledSkillConfig,
    EnabledSkillsConfig,
    MCPDiscoveredTool,
    MCPServerConfig,
    MCPServersConfig,
    prepare_mcp_tool,
)
from agent_factory.tooling.skills import parse_skill_directory
from agent_factory.tooling.skillhub.service import SkillHubService
from agent_factory.tooling.runtime_settings import (
    ToolRuntimeOverride,
    ToolRuntimeSettings,
    load_tool_runtime_settings,
    tool_runtime_settings_path,
)


TOOL_PERMISSIONS_FILENAME = "tool_permissions.json"


@dataclass(frozen=True, slots=True)
class ExtensionManageResult:
    payload: dict[str, Any]
    changed: bool = False


class AgentPackageExtensionService:
    def __init__(self) -> None:
        self._operation_lock = threading.RLock()
        self._operations: dict[str, MCPRuntimeOperation] = {}

    def summary(self, package_id: str, package: LoadedAgentPackage) -> dict[str, Any]:
        extension_root = extension_root_for_package(package_id, package)
        return _extension_summary(
            scope_id=package_id,
            extension_root=extension_root,
            package=package,
        )

    def system_summary(self, owner: SystemAgentExtensionOwner) -> dict[str, Any]:
        return _extension_summary(
            scope_id=owner,
            extension_root=default_system_agent_extension_root(owner),
            system_owner=owner,
        )

    def system_manage(
        self,
        owner: SystemAgentExtensionOwner,
        action: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        progress: Callable[[str, str], None] | None = None,
    ) -> ExtensionManageResult:
        return self._manage_with_operation(
            action=action,
            request_id=request_id,
            progress=progress,
            manage=lambda operation: _manage_extension_root(
                scope_id=owner,
                extension_root=default_system_agent_extension_root(owner),
                action=action,
                payload=payload,
                system_owner=owner,
                operation=operation,
            ),
        )

    def manage(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        action: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        progress: Callable[[str, str], None] | None = None,
    ) -> ExtensionManageResult:
        return self._manage_with_operation(
            action=action,
            request_id=request_id,
            progress=progress,
            manage=lambda operation: _manage_extension_root(
                scope_id=package_id,
                extension_root=extension_root_for_package(package_id, package),
                action=action,
                payload=payload,
                package=package,
                operation=operation,
            ),
        )

    def cancel_operation(self, request_id: str | None) -> bool:
        if not request_id:
            return False
        with self._operation_lock:
            operation = self._operations.get(request_id)
        return operation.cancel() if operation is not None else False

    def _manage_with_operation(
        self,
        *,
        action: str,
        request_id: str | None,
        progress: Callable[[str, str], None] | None,
        manage: Callable[[MCPRuntimeOperation | None], ExtensionManageResult],
    ) -> ExtensionManageResult:
        if action not in {"install_mcp", "test_mcp"} or not request_id:
            return manage(None)
        operation = MCPRuntimeOperation(
            wait_without_deadline=True,
            stderr_callback=(
                lambda server, line: progress(
                    server.server_id,
                    _redact_mcp_test_text(line, [*server.env.values(), *server.headers.values()]),
                )
                if progress is not None
                else None
            ),
        )
        with self._operation_lock:
            self._operations[request_id] = operation
        try:
            return manage(operation)
        finally:
            with self._operation_lock:
                if self._operations.get(request_id) is operation:
                    self._operations.pop(request_id, None)


def _extension_summary(
    *,
    scope_id: str,
    extension_root: Path,
    package: LoadedAgentPackage | None = None,
    system_owner: SystemAgentExtensionOwner | None = None,
) -> dict[str, Any]:
    bundle = _load_effective_extension_bundle(
        extension_root,
        package=package,
        system_owner=system_owner,
    )
    return {
        "package_id": scope_id,
        "resource_mode": system_owner or "package",
        "mcp_servers": [
            public_mcp_server(server.model_dump(mode="json"))
            for server in load_registered_mcp_servers().servers
        ],
        "skills": [
            public_skill(skill.model_dump(mode="json"))
            for skill in load_resolved_registered_skills().skills
        ],
        "bindings": registered_agent_extension_bindings(
            [
                *(
                    _system_extension_inherited_roots(extension_root)
                    if system_owner is not None
                    else _extension_inherited_roots(extension_root, package=package)
                ),
                extension_root,
            ]
        ).model_dump(mode="json"),
        "tool_permissions": _tool_permissions_view(
            package=package,
            extension_root=extension_root,
            bundle=bundle,
            system_owner=system_owner,
        ),
        "sources": {
            "extension_root": str(bundle.sources.extension_root),
            "mcp_servers_paths": [str(registry_mcp_path())],
            "enabled_skills_paths": [str(registry_skills_path())],
            "tool_permissions_path": str(extension_root / TOOL_PERMISSIONS_FILENAME),
            "tool_settings_path": str(tool_runtime_settings_path(extension_root)),
        },
    }


def _manage_extension_root(
    *,
    scope_id: str,
    extension_root: Path,
    action: str,
    payload: dict[str, Any],
    package: LoadedAgentPackage | None = None,
    system_owner: SystemAgentExtensionOwner | None = None,
    operation: MCPRuntimeOperation | None = None,
) -> ExtensionManageResult:
    def summary() -> dict[str, Any]:
        return _extension_summary(
            scope_id=scope_id,
            extension_root=extension_root,
            package=package,
            system_owner=system_owner,
        )

    if action == "list":
        return ExtensionManageResult(summary())
    if action == "set_binding":
        kind = str(payload.get("kind") or "").strip()
        if kind not in {"mcp", "skill"}:
            raise ValueError("extension binding kind must be mcp or skill")
        identifier = str(payload.get("identifier") or "").strip()
        bindings = set_agent_extension_binding(
            extension_root,
            kind=kind,
            identifier=identifier,
            enabled=bool(payload.get("enabled", True)),
            inherited_extension_roots=(
                _system_extension_inherited_roots(extension_root)
                if system_owner is not None
                else _extension_inherited_roots(extension_root, package=package)
            ),
        )
        return ExtensionManageResult(
            {
                "updated": "binding",
                "bindings": bindings.model_dump(mode="json"),
                **summary(),
            },
            changed=True,
        )
    if action == "get_mcp_config":
        server_id = _required_config_id(payload, "server_id")
        server = _find_mcp_server(
            extension_root,
            server_id,
            package=package,
            system_owner=system_owner,
        )
        if server is None:
            raise ValueError(f"MCP server is not configured: {server_id}")
        return ExtensionManageResult(
            {
                "server_config": server.model_dump(mode="json"),
                **summary(),
            }
        )
    if action == "upsert_mcp":
        server = _mcp_server_for_upsert(
            extension_root,
            payload,
            package=package,
            system_owner=system_owner,
        )
        _save_mcp_server(extension_root, server)
        return ExtensionManageResult(
            {
                "updated": "mcp",
                "server": public_mcp_server(server.model_dump(mode="json")),
                **summary(),
            },
            changed=True,
        )
    if action == "install_mcp":
        return _install_mcp_servers(
            extension_root,
            payload,
            summary=summary,
            package=package,
            system_owner=system_owner,
            operation=operation,
        )
    if action == "remove_mcp":
        server_id = _required_config_id(payload, "server_id")
        removed = _remove_mcp_server(extension_root, server_id=server_id)
        return ExtensionManageResult(
            {"updated": "mcp", "removed": removed, **summary()},
            changed=True,
        )
    if action == "test_mcp":
        server = _mcp_server_for_test(
            extension_root,
            payload,
            package=package,
            system_owner=system_owner,
        )
        return ExtensionManageResult({"test": _test_mcp_server(server), **summary()})
    if action == "update_tool_permissions":
        policy = _tool_approval_policy_from_payload(payload)
        _write_tool_permission_policy(extension_root, policy)
        return ExtensionManageResult(
            {"updated": "tool_permissions", **summary()},
            changed=True,
        )
    if action == "set_tool_permission":
        policy = _load_tool_permission_policy(extension_root)
        tool_id = _tool_permission_id(payload)
        override_payload = payload.get("override") if isinstance(payload.get("override"), dict) else payload
        next_overrides = dict(policy.tool_overrides)
        next_overrides[tool_id] = _tool_override_from_payload(override_payload)
        policy = ToolApprovalPolicyConfig.model_validate(
            policy.model_copy(update={"tool_overrides": next_overrides}).model_dump(mode="json")
        )
        _write_tool_permission_policy(extension_root, policy)
        return ExtensionManageResult(
            {"updated": "tool_permissions", **summary()},
            changed=True,
        )
    if action == "reset_tool_permission":
        policy = _load_tool_permission_policy(extension_root)
        tool_id = _tool_permission_id(payload)
        next_overrides = dict(policy.tool_overrides)
        next_overrides.pop(tool_id, None)
        policy = ToolApprovalPolicyConfig.model_validate(
            policy.model_copy(update={"tool_overrides": next_overrides}).model_dump(mode="json")
        )
        _write_tool_permission_policy(extension_root, policy)
        return ExtensionManageResult(
            {"updated": "tool_permissions", **summary()},
            changed=True,
        )
    if action == "update_tool_configuration":
        tool_id = _tool_permission_id(payload)
        current_summary = summary()
        permission_tools = current_summary.get("tool_permissions", {}).get("tools", [])
        current_tool = next(
            (
                item
                for item in permission_tools
                if isinstance(item, dict) and str(item.get("tool_id") or "") == tool_id
            ),
            None,
        )
        if current_tool is None:
            raise ValueError(f"tool is not available for this agent: {tool_id}")
        policy = _load_tool_permission_policy(extension_root)
        settings = load_tool_runtime_settings(extension_root)
        existing_permission = policy.tool_overrides.get(tool_id, ToolApprovalOverrideConfig())
        approval_payload = {
            "approval": payload.get("approval", existing_permission.approval),
            "risk_level": payload.get("risk_level", existing_permission.risk_level),
        }
        permission_override = ToolApprovalOverrideConfig.model_validate(approval_payload)
        next_permission_overrides = dict(policy.tool_overrides)
        if permission_override.approval == "inherit" and permission_override.risk_level is None:
            next_permission_overrides.pop(tool_id, None)
        else:
            next_permission_overrides[tool_id] = permission_override
        next_policy = ToolApprovalPolicyConfig.model_validate(
            policy.model_copy(update={"tool_overrides": next_permission_overrides}).model_dump(mode="json")
        )
        existing_runtime = settings.tools.get(tool_id, ToolRuntimeOverride())
        runtime_description = existing_runtime.description
        if "description" in payload:
            submitted_description = ToolRuntimeOverride(description=payload.get("description")).description
            runtime_description = (
                None
                if submitted_description == str(current_tool.get("base_description") or "").strip()
                else submitted_description
            )
        runtime_max_model_chars = existing_runtime.max_model_chars
        if "max_model_chars" in payload:
            submitted_max_model_chars = ToolRuntimeOverride(
                max_model_chars=payload.get("max_model_chars")
            ).max_model_chars
            runtime_max_model_chars = (
                None
                if submitted_max_model_chars == int(current_summary["tool_permissions"]["default_max_model_chars"])
                else submitted_max_model_chars
            )
        runtime_concurrent = existing_runtime.concurrent
        if "concurrent" in payload:
            submitted_concurrent = ToolRuntimeOverride(concurrent=payload.get("concurrent")).concurrent
            runtime_concurrent = (
                None
                if submitted_concurrent == bool(current_tool.get("base_concurrent", True))
                else submitted_concurrent
            )
        runtime_override = ToolRuntimeOverride(
            description=runtime_description,
            max_model_chars=runtime_max_model_chars,
            concurrent=runtime_concurrent,
        )
        next_tool_settings = dict(settings.tools)
        if (
            runtime_override.description is None
            and runtime_override.max_model_chars is None
            and runtime_override.concurrent is None
        ):
            next_tool_settings.pop(tool_id, None)
        else:
            next_tool_settings[tool_id] = runtime_override
        next_settings = ToolRuntimeSettings.model_validate(
            settings.model_copy(update={"tools": next_tool_settings}).model_dump(mode="json")
        )
        write_json_objects_atomically(
            {
                extension_root / TOOL_PERMISSIONS_FILENAME: _tool_permission_document(next_policy),
                tool_runtime_settings_path(extension_root): next_settings.model_dump(mode="json"),
            }
        )
        return ExtensionManageResult(
            {"updated": "tool_configuration", **summary()},
            changed=True,
        )
    if action == "reset_tool_configuration":
        tool_id = _tool_permission_id(payload)
        policy = _load_tool_permission_policy(extension_root)
        settings = load_tool_runtime_settings(extension_root)
        next_permission_overrides = dict(policy.tool_overrides)
        next_permission_overrides.pop(tool_id, None)
        next_tool_settings = dict(settings.tools)
        next_tool_settings.pop(tool_id, None)
        next_policy = ToolApprovalPolicyConfig.model_validate(
            policy.model_copy(update={"tool_overrides": next_permission_overrides}).model_dump(mode="json")
        )
        next_settings = ToolRuntimeSettings.model_validate(
            settings.model_copy(update={"tools": next_tool_settings}).model_dump(mode="json")
        )
        write_json_objects_atomically(
            {
                extension_root / TOOL_PERMISSIONS_FILENAME: _tool_permission_document(next_policy),
                tool_runtime_settings_path(extension_root): next_settings.model_dump(mode="json"),
            }
        )
        return ExtensionManageResult(
            {"updated": "tool_configuration", **summary()},
            changed=True,
        )
    if action == "upsert_skill":
        skill_payload = payload.get("skill") if isinstance(payload.get("skill"), dict) else payload
        replace_skill_id = str(
            payload.get("replace_skill_id")
            or skill_payload.get("replace_skill_id")
            or ""
        ).strip()
        skill = _save_managed_skill_from_payload(
            skill_payload,
            replace_skill_id=replace_skill_id,
        )
        return ExtensionManageResult(
            {
                "updated": "skill",
                "skill": public_skill(skill.model_dump(mode="json")),
                **summary(),
            },
            changed=True,
        )
    if action in {"skillhub_status", "skillhub_search", "skillhub_install"}:
        skillhub_action = action.removeprefix("skillhub_")
        result = SkillHubService(extension_root=default_extension_registry_root()).run(
            {
                "action": skillhub_action,
                "query": payload.get("query"),
                "skill": payload.get("skill"),
            }
        )
        changed = skillhub_action == "install"
        return ExtensionManageResult(
            {
                "skillhub": result,
                **summary(),
            },
            changed=changed,
        )
    if action == "remove_skill":
        skill_id = _required_config_id(payload, "skill_id")
        removed = _remove_skill(extension_root, skill_id=skill_id)
        return ExtensionManageResult(
            {"updated": "skill", "removed": removed, **summary()},
            changed=True,
        )
    raise ValueError(f"unsupported extensions action: {action}")


def extensions_summary(package_id: str, *, package: LoadedAgentPackage | None = None) -> dict[str, str]:
    host_root = (
        extension_root_for_package(package_id, package)
        if package is not None
        else host_runtime_root(package_id) / "extensions"
    )
    return {
        "host_root": str(host_root),
        "runtime_root": str(host_root),
    }


def package_extension_detail(*, package_id: str, package: LoadedAgentPackage) -> dict[str, Any]:
    extension_root = extension_root_for_package(package_id, package)
    try:
        bundle = load_extension_bundle(extension_root, package=package)
        return {
            "mcp_servers": [
                public_mcp_server(server.model_dump(mode="json"))
                for server in bundle.mcp_servers.servers
            ],
            "skills": [
                public_skill(skill.model_dump(mode="json"))
                for skill in bundle.enabled_skills.skills
            ],
        }
    except Exception as exc:
        return {
            "mcp_servers": [],
            "skills": [],
            "extensions_error": f"{type(exc).__name__}: {exc}",
        }


def _tool_permissions_view(
    *,
    package: LoadedAgentPackage | None,
    extension_root: Path,
    bundle: Any,
    system_owner: SystemAgentExtensionOwner | None = None,
) -> dict[str, Any]:
    policy = _load_tool_permission_policy(extension_root)
    settings = load_tool_runtime_settings(extension_root)
    tools = _tool_permission_tools(package=package, bundle=bundle, system_owner=system_owner)
    default_max_model_chars = default_tool_output_policy().max_model_chars
    return {
        "policy": policy.model_dump(mode="json"),
        "default_max_model_chars": default_max_model_chars,
        "tools": [
            _tool_with_runtime_settings(
                tool,
                settings.tools.get(str(tool.get("tool_id") or "")),
                default_max_model_chars=default_max_model_chars,
            )
            for tool in tools
        ],
    }


def _load_tool_permission_policy(extension_root: Path) -> ToolApprovalPolicyConfig:
    payload = read_json_object(extension_root / TOOL_PERMISSIONS_FILENAME)
    policy_payload = payload.get("policy", payload) if payload else {}
    return ToolApprovalPolicyConfig.model_validate(policy_payload if isinstance(policy_payload, dict) else {})


def _write_tool_permission_policy(extension_root: Path, policy: ToolApprovalPolicyConfig) -> None:
    write_json_object(extension_root / TOOL_PERMISSIONS_FILENAME, _tool_permission_document(policy))


def _tool_permission_document(policy: ToolApprovalPolicyConfig) -> dict[str, Any]:
    return {
        "version": "tool_permissions.v0",
        "policy": policy.model_dump(mode="json"),
    }


def _tool_approval_policy_from_payload(payload: dict[str, Any]) -> ToolApprovalPolicyConfig:
    policy_payload = payload.get("policy") if isinstance(payload.get("policy"), dict) else payload
    return ToolApprovalPolicyConfig.model_validate(policy_payload or {})


def _tool_override_from_payload(payload: dict[str, Any]) -> ToolApprovalOverrideConfig:
    return ToolApprovalOverrideConfig.model_validate(payload or {})


def _tool_permission_id(payload: dict[str, Any]) -> str:
    return _required_config_id(payload, "tool_id").lower().replace("-", "_")


def _tool_permission_tools(
    *,
    package: LoadedAgentPackage | None,
    bundle: Any,
    system_owner: SystemAgentExtensionOwner | None = None,
) -> list[dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    if package is None:
        for item in _system_agent_permission_tools(system_owner):
            tools[item["tool_id"]] = item
    else:
        for item in _builtin_permission_tools(package):
            tools[item["tool_id"]] = item
        for spec in package.assembly_spec.tools:
            item = _public_tool_permission_item(
                tool_id=str(getattr(spec, "id", "") or ""),
                name=humanize_identifier(str(getattr(spec, "id", "") or "")) or "Package Tool",
                description=str(getattr(spec, "description", "") or ""),
                source="package",
                risk_level=str(getattr(spec, "risk_level", "") or "low"),
                permission_scope=str(getattr(spec, "permission_scope", "") or "package"),
                permission_tags=list(getattr(spec, "permission_tags", []) or []),
                concurrent=bool(getattr(spec, "concurrent", True)),
            )
            if item:
                tools[item["tool_id"]] = item
        for item in _model_permission_tools(package):
            tools[item["tool_id"]] = item
    if getattr(bundle.enabled_skills, "skills", None):
        tools["skill"] = _public_tool_permission_item(
            tool_id="skill",
            name="Skill",
            description="Read and use enabled Skill resources for this agent.",
            source="extension",
            risk_level="medium",
            permission_scope="extension",
            permission_tags=[],
            concurrent=True,
        )
    catalog = load_registered_mcp_tool_catalog()
    for server in getattr(bundle.mcp_servers, "servers", []):
        for registered_tool in catalog.servers.get(server.server_id, []):
            item = _public_tool_permission_item(
                tool_id=registered_tool.tool_id,
                name=registered_tool.name,
                description=registered_tool.description,
                source="mcp",
                risk_level=registered_tool.risk_level,
                permission_scope=registered_tool.permission_scope,
                permission_tags=registered_tool.permission_tags,
                concurrent=registered_tool.concurrent,
            )
            if item:
                tools[item["tool_id"]] = item
    return sorted(tools.values(), key=lambda item: (str(item.get("source") or ""), str(item.get("tool_id") or "")))


def _model_permission_tools(package: LoadedAgentPackage) -> list[dict[str, Any]]:
    contract = package.contracts.get("model") if isinstance(package.contracts, dict) else None
    config = contract.get("config") if isinstance(contract, dict) else None
    bindings = config.get("tool_bindings") if isinstance(config, dict) else None
    tools: list[dict[str, Any]] = []
    for tool_id, binding in (bindings.items() if isinstance(bindings, dict) else []):
        if not isinstance(binding, dict):
            continue
        display_name = humanize_identifier(str(tool_id)) or str(tool_id)
        item = _public_tool_permission_item(
            tool_id=str(tool_id),
            name=display_name,
            description=str(
                binding.get("description")
                or f"Invoke the {display_name} model capability for this agent."
            ),
            source="model",
            risk_level="low",
            permission_scope="model",
            permission_tags=[],
            concurrent=str(binding.get("capability") or "") not in {"image_output", "image_edit"},
        )
        if item:
            tools.append(item)
    return tools


def _system_agent_permission_tools(system_owner: SystemAgentExtensionOwner | None) -> list[dict[str, Any]]:
    try:
        from agent_factory.create_agent.tooling import (
            CREATE_AGENT_ASSIST_TOOL_IDS,
            CREATE_AGENT_BUILTIN_TOOL_IDS,
            build_create_agent_authoring_tool_spec,
            build_create_agent_control_tool_spec,
            build_create_agent_probe_tool_spec,
            build_create_agent_stage_tool_spec,
            build_create_agent_validate_tool_spec,
            build_model_pool_select_tool_spec,
        )
        from agent_factory.tooling.builtins.registry import (
            get_always_available_system_tool_ids,
            get_builtin_tool_specs,
            get_read_only_system_tool_ids,
        )
    except Exception:
        return []
    authoring_specs = [
        build_create_agent_authoring_tool_spec(),
        build_create_agent_control_tool_spec(),
        build_model_pool_select_tool_spec(),
        build_create_agent_probe_tool_spec(),
        build_create_agent_validate_tool_spec(),
    ]
    if system_owner == "create_agent":
        authoring_specs.append(build_create_agent_stage_tool_spec())
    builtin_ids = CREATE_AGENT_BUILTIN_TOOL_IDS if system_owner in {"create_agent", "evolve_agent"} else CREATE_AGENT_ASSIST_TOOL_IDS
    read_only_ids = get_read_only_system_tool_ids()
    allowed_builtin_ids = set(builtin_ids) | set(get_always_available_system_tool_ids())
    tools: list[dict[str, Any]] = []
    for spec in get_builtin_tool_specs():
        if spec.id not in allowed_builtin_ids:
            continue
        item = _public_tool_permission_item(
            tool_id=spec.id,
            name=humanize_identifier(spec.id) or spec.id,
            description=spec.description,
            source="system",
            risk_level=spec.risk_level,
            permission_scope="system",
            permission_tags=["read_only"] if spec.id in read_only_ids else [],
            concurrent=spec.concurrent,
        )
        if item:
            tools.append(item)
    for spec in sorted(authoring_specs, key=lambda item: item.id):
        item = _public_tool_permission_item(
            tool_id=spec.id,
            name=humanize_identifier(spec.id) or spec.id,
            description=spec.description,
            source="system",
            risk_level=spec.risk_level,
            permission_scope=spec.permission_scope,
            permission_tags=spec.permission_tags,
            concurrent=spec.concurrent,
        )
        if item:
            tools.append(item)
    return tools


def _builtin_permission_tools(package: LoadedAgentPackage) -> list[dict[str, Any]]:
    config = _tools_contract_config(package)
    if config.get("builtin_tools_enabled") is False:
        return []
    configured_ids = [str(item) for item in config.get("builtin_tool_ids") or [] if str(item).strip()]
    try:
        from agent_factory.tooling.builtins.aliases import canonical_builtin_tool_ids
        from agent_factory.tooling.builtins.registry import (
            get_always_available_system_tool_ids,
            get_builtin_tool_specs,
            get_read_only_system_tool_ids,
        )
    except Exception:
        return []
    always_available = get_always_available_system_tool_ids()
    read_only_ids = get_read_only_system_tool_ids()
    allowed_ids = set(canonical_builtin_tool_ids(configured_ids))
    specs = get_builtin_tool_specs()
    if allowed_ids:
        specs = [spec for spec in specs if spec.id in allowed_ids or spec.id in always_available]
    tools: list[dict[str, Any]] = []
    for spec in specs:
        item = _public_tool_permission_item(
            tool_id=spec.id,
            name=humanize_identifier(spec.id) or spec.id,
            description=spec.description,
            source="system",
            risk_level=spec.risk_level,
            permission_scope="system",
            permission_tags=["read_only"] if spec.id in read_only_ids else [],
            concurrent=spec.concurrent,
        )
        if item:
            tools.append(item)
    return tools


def _tools_contract_config(package: LoadedAgentPackage) -> dict[str, Any]:
    contract = package.contracts.get("tools") if isinstance(package.contracts, dict) else None
    config = contract.get("config") if isinstance(contract, dict) else None
    return dict(config) if isinstance(config, dict) else {}


def _public_tool_permission_item(
    *,
    tool_id: str,
    name: str,
    description: str,
    source: str,
    risk_level: str,
    permission_scope: str,
    permission_tags: list[str],
    concurrent: bool,
) -> dict[str, Any] | None:
    normalized_tool_id = str(tool_id or "").strip()
    if not normalized_tool_id:
        return None
    return {
        "tool_id": normalized_tool_id,
        "name": name,
        "description": description,
        "source": source,
        "risk_level": risk_level,
        "permission_scope": permission_scope,
        "permission_tags": permission_tags,
        "concurrent": concurrent,
    }


def _tool_with_runtime_settings(
    tool: dict[str, Any],
    override: ToolRuntimeOverride | None,
    *,
    default_max_model_chars: int,
) -> dict[str, Any]:
    base_description = str(tool.get("description") or "").strip()
    base_concurrent = bool(tool.get("concurrent", True))
    return {
        **tool,
        "base_description": base_description,
        "description": override.description if override is not None and override.description else base_description,
        "description_overridden": bool(override is not None and override.description),
        "base_concurrent": base_concurrent,
        "concurrent": override.concurrent if override is not None and override.concurrent is not None else base_concurrent,
        "concurrent_overridden": bool(override is not None and override.concurrent is not None),
        "max_model_chars": (
            override.max_model_chars
            if override is not None and override.max_model_chars is not None
            else default_max_model_chars
        ),
        "max_model_chars_overridden": bool(override is not None and override.max_model_chars is not None),
    }


def load_extension_bundle(extension_root: Path, *, package: LoadedAgentPackage | None = None) -> Any:
    return AgentInstanceExtensionConfigLoader(
        extension_root,
        inherited_extension_roots=_extension_inherited_roots(extension_root, package=package),
    ).load()


def load_system_agent_extension_bundle(extension_root: Path) -> Any:
    return AgentInstanceExtensionConfigLoader(
        extension_root,
        inherited_extension_roots=_system_extension_inherited_roots(extension_root),
    ).load()


def _system_extension_inherited_roots(extension_root: Path) -> list[Path]:
    builtin_root = default_builtin_factory_extension_root()
    return [] if builtin_root.resolve() == extension_root.resolve() else [builtin_root]


def _load_effective_extension_bundle(
    extension_root: Path,
    *,
    package: LoadedAgentPackage | None = None,
    system_owner: SystemAgentExtensionOwner | None = None,
) -> Any:
    if system_owner is not None:
        return load_system_agent_extension_bundle(extension_root)
    return load_extension_bundle(extension_root, package=package)


def public_mcp_server(payload: dict[str, Any]) -> dict[str, Any]:
    server_id = str(payload.get("server_id") or "").strip()
    source = dict(payload.get("source") or {})
    enabled = payload.get("enabled", True) is not False
    env = payload.get("env") if isinstance(payload.get("env"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    name = str(source.get("package") or source.get("name") or humanize_identifier(server_id) or "MCP server")
    description = str(source.get("description") or source.get("summary") or "").strip()
    safe_payload = {
        "server_id": server_id,
        "display_name": name,
        "description": description,
        "transport": payload.get("transport"),
        "command": payload.get("command"),
        "args": list(payload.get("args") or []),
        "cwd": payload.get("cwd"),
        "url": payload.get("url"),
        "source": source,
        "enabled": enabled,
        "required": bool(payload.get("required")),
        "tool_id_prefix": payload.get("tool_id_prefix"),
        "risk_level_default": payload.get("risk_level_default"),
        "timeout_seconds": payload.get("timeout_seconds"),
        "env_keys": sorted(str(key) for key in env),
        "header_keys": sorted(str(key) for key in headers),
    }
    return {
        "kind": "mcp",
        "name": name,
        "scope": str(source.get("type") or "local"),
        "status": "enabled" if enabled else "disabled",
        "enabled": enabled,
        "transport": payload.get("transport"),
        "summary": description or _mcp_server_summary(payload),
        "payload": safe_payload,
    }


def public_skill(payload: dict[str, Any]) -> dict[str, Any]:
    skill_id = str(payload.get("skill_id") or "").strip()
    enabled = payload.get("enabled", True) is not False
    metadata = _skill_metadata_for_public_view(payload)
    name = metadata.get("name") or skill_id
    description = str(metadata.get("description") or "").strip()
    return {
        "kind": "skill",
        "name": humanize_identifier(str(name)) or "Skill",
        "scope": str(payload.get("source") or "local"),
        "status": "enabled" if enabled else "disabled",
        "enabled": enabled,
        "summary": description or _skill_summary(payload),
        "payload": {
            "skill_id": skill_id,
            "description": description,
            "enabled": enabled,
            "source": payload.get("source"),
            "path": payload.get("path"),
            "required": bool(payload.get("required")),
            "resource_count": metadata.get("resource_count"),
            "script_count": metadata.get("script_count"),
        },
    }


def _extension_inherited_roots(extension_root: Path, *, package: LoadedAgentPackage | None) -> list[Path]:
    if package is None:
        return []
    roots: list[Path] = []
    if is_system_package(package):
        builtin_root = default_builtin_agent_extension_root()
        if builtin_root.resolve() != extension_root.resolve():
            roots.append(builtin_root)
    package_extension_root = package.package_root / "extensions"
    if package_extension_root.resolve() != extension_root.resolve():
        roots.append(package_extension_root)
    return roots


def _load_local_skills_config(extension_root: Path) -> EnabledSkillsConfig:
    return load_registered_skills()


def _save_mcp_server(extension_root: Path, server: MCPServerConfig) -> None:
    remove_registered_mcp_tool_catalog(server.server_id)
    upsert_registered_mcp_servers([server])


def _save_mcp_servers(extension_root: Path, servers: list[MCPServerConfig]) -> None:
    upsert_registered_mcp_servers(servers)


def _remove_mcp_server(extension_root: Path, *, server_id: str) -> bool:
    return remove_registered_extension("mcp", server_id)


def _save_enabled_skill(extension_root: Path, skill: EnabledSkillConfig) -> None:
    upsert_registered_skill(skill)


def _save_managed_skill_from_payload(
    payload: dict[str, Any],
    *,
    replace_skill_id: str,
) -> EnabledSkillConfig:
    raw = dict(payload or {})
    path = str(raw.get("path") or "").strip()
    if not path:
        raise ValueError("Skill path is required")
    source = str(raw.get("source") or "local").strip() or "local"
    registry_root = default_extension_registry_root()
    resolved = Path(_skill_path_for_validation(path, registry_root)).resolve()
    try:
        resolved.relative_to((registry_root / "skills").resolve())
    except ValueError:
        return import_registered_skill_directory(
            resolved,
            enabled=raw.get("enabled", True) is not False,
            required=bool(raw.get("required")),
            source_kind=source,
            replace_skill_id=replace_skill_id or None,
        )
    skill = _skill_from_payload(raw, extension_root=registry_root)
    if replace_skill_id and replace_skill_id != skill.skill_id:
        raise ValueError(
            "Managed Skill identity cannot be changed without selecting a new Skill folder"
        )
    _save_enabled_skill(registry_root, skill)
    return skill


def _remove_enabled_skill(extension_root: Path, *, skill_id: str) -> bool:
    return remove_registered_extension("skill", skill_id)


def _remove_skill(extension_root: Path, *, skill_id: str) -> dict[str, Any]:
    config = _load_local_skills_config(extension_root)
    targets = [skill for skill in config.skills if skill.skill_id == skill_id]
    removed_from_config = _remove_enabled_skill(extension_root, skill_id=skill_id)
    removed_paths: list[str] = []
    missing_paths: list[str] = []
    for skill in targets:
        path = _resolved_skill_path(extension_root, skill)
        if not _can_remove_skill_path(extension_root, path):
            continue
        if path.exists():
            shutil.rmtree(path)
            removed_paths.append(str(path))
        else:
            missing_paths.append(str(path))
    return {
        "skill_id": skill_id,
        "config": removed_from_config,
        "paths": removed_paths,
        "missing_paths": missing_paths,
    }


def _resolved_skill_path(extension_root: Path, skill: EnabledSkillConfig) -> Path:
    path = Path(skill.path).expanduser()
    if not path.is_absolute():
        path = extension_root / path
    return path.resolve()


def _can_remove_skill_path(extension_root: Path, path: Path) -> bool:
    skills_root = (extension_root / "skills").resolve()
    try:
        path.resolve().relative_to(skills_root)
    except ValueError:
        return False
    return path.resolve() != skills_root


def _mcp_server_for_upsert(
    extension_root: Path,
    payload: dict[str, Any],
    *,
    package: LoadedAgentPackage | None = None,
    system_owner: SystemAgentExtensionOwner | None = None,
) -> MCPServerConfig:
    server_payload = payload.get("server") if isinstance(payload.get("server"), dict) else payload
    server_id = str(server_payload.get("server_id") or "").strip()
    existing = (
        _find_mcp_server(
            extension_root,
            server_id,
            package=package,
            system_owner=system_owner,
        )
        if server_id
        else None
    )
    return _mcp_server_from_payload(server_payload, existing=existing)


def _find_mcp_server(
    extension_root: Path,
    server_id: str,
    *,
    package: LoadedAgentPackage | None = None,
    system_owner: SystemAgentExtensionOwner | None = None,
) -> MCPServerConfig | None:
    if not server_id:
        return None
    return find_registered_mcp_server(server_id)


def _mcp_server_for_test(
    extension_root: Path,
    payload: dict[str, Any],
    *,
    package: LoadedAgentPackage | None = None,
    system_owner: SystemAgentExtensionOwner | None = None,
) -> MCPServerConfig:
    server_payload = payload.get("server") if isinstance(payload.get("server"), dict) else payload
    server_id = str(server_payload.get("server_id") or "").strip()
    if server_id:
        existing = _find_mcp_server(
            extension_root,
            server_id,
            package=package,
            system_owner=system_owner,
        )
        if existing is not None:
            return _mcp_server_from_payload(server_payload, existing=existing)
    return _mcp_server_from_payload(server_payload)


def _mcp_server_from_payload(payload: dict[str, Any], *, existing: MCPServerConfig | None = None) -> MCPServerConfig:
    raw = dict(payload or {})
    existing_source = dict(existing.source) if existing is not None else {}
    source = {**existing_source, **dict(raw.get("source") or {})}
    display_name = str(raw.get("display_name") or raw.get("name") or source.get("name") or "").strip()
    if display_name:
        source["name"] = display_name
    description = str(raw.get("description") or raw.get("summary") or source.get("description") or "").strip()
    if description:
        source["description"] = description
    command = str(raw.get("command") if "command" in raw else existing.command if existing is not None else "").strip()
    args = _parse_args(raw["args"]) if "args" in raw else list(existing.args) if existing is not None else []
    cwd_value = raw.get("cwd") if "cwd" in raw else existing.cwd if existing is not None else None
    cwd = str(cwd_value or "").strip() or None
    env = _parse_env(raw["env"]) if "env" in raw else dict(existing.env) if existing is not None else {}
    url_value = raw.get("url") if "url" in raw else existing.url if existing is not None else None
    url = str(url_value or "").strip() or None
    headers = _parse_env(raw["headers"]) if "headers" in raw else dict(existing.headers) if existing is not None else {}
    enabled = raw.get("enabled") if "enabled" in raw else existing.enabled if existing is not None else True
    server_id = _config_identifier(
        str(raw.get("server_id") or ""),
        fallback=display_name or str(source.get("package") or "") or command or "mcp_server",
    )
    tool_id_prefix = raw.get(
        "tool_id_prefix",
        existing.tool_id_prefix if existing is not None else None,
    )
    return MCPServerConfig(
        server_id=server_id,
        transport=str(raw.get("transport") or (existing.transport if existing is not None else "stdio")).strip(),
        command=command or None,
        args=args,
        cwd=cwd,
        env=env,
        url=url,
        headers=headers,
        source=source,
        enabled=enabled is not False,
        required=bool(raw.get("required") if "required" in raw else existing.required if existing is not None else False),
        tool_id_prefix=_optional_identifier(tool_id_prefix),
        risk_level_default=str(raw.get("risk_level_default") or (existing.risk_level_default if existing is not None else "medium")),
        concurrent_default=bool(raw.get("concurrent_default") if "concurrent_default" in raw else existing.concurrent_default if existing is not None else False),
        timeout_seconds=float(raw.get("timeout_seconds") or (existing.timeout_seconds if existing is not None else 30.0)),
        tool_input_property_enums=(
            dict(raw.get("tool_input_property_enums") or {})
            if "tool_input_property_enums" in raw
            else dict(existing.tool_input_property_enums) if existing is not None else {}
        ),
        tool_loop_policies=(
            dict(raw.get("tool_loop_policies") or {})
            if "tool_loop_policies" in raw
            else dict(existing.tool_loop_policies) if existing is not None else {}
        ),
        tool_description_contexts=(
            dict(raw.get("tool_description_contexts") or {})
            if "tool_description_contexts" in raw
            else dict(existing.tool_description_contexts) if existing is not None else {}
        ),
    )


def _skill_from_payload(payload: dict[str, Any], *, extension_root: Path | None = None) -> EnabledSkillConfig:
    raw = dict(payload or {})
    path = str(raw.get("path") or "").strip()
    if not path:
        raise ValueError("Skill path is required")
    source = str(raw.get("source") or "local").strip() or "local"
    skill_id = str(raw.get("skill_id") or "").strip()
    if not skill_id:
        skill = parse_skill_directory(_skill_path_for_validation(path, extension_root))
        skill_id = skill.name
    return EnabledSkillConfig(
        skill_id=skill_id,
        enabled=raw.get("enabled", True) is not False,
        source=source,
        path=path,
        required=bool(raw.get("required")),
    )


def _skill_path_for_validation(path: str, extension_root: Path | None) -> str:
    skill_path = Path(path).expanduser()
    if not skill_path.is_absolute() and extension_root is not None:
        skill_path = extension_root / skill_path
    return str(skill_path)


def _test_mcp_server(
    server: MCPServerConfig,
    *,
    operation: MCPRuntimeOperation | None = None,
) -> dict[str, Any]:
    preflight = _mcp_server_preflight(server)
    if preflight["status"] != "ok":
        return {**preflight, "tool_count": 0, "tools": []}
    manager = MCPRuntimeManager(
        MCPServersConfig(servers=[server.model_copy(update={"enabled": True})]),
        operation=operation,
    )
    client = manager.clients().get(server.server_id)
    if client is None:
        return {"status": "failed", "message": "MCP server is disabled or unavailable", "tool_count": 0, "tools": []}
    try:
        discovered_tools = list(client.list_tools())
    except BaseException as exc:
        if exception_contains(exc, MCPRuntimeCancelled):
            failure = _mcp_test_failure(
                exc,
                stderr=client.stderr_logs(),
                sensitive_values=[*server.env.values(), *server.headers.values()],
            )
            return {**failure, "status": "cancelled", "message": str(exc)}
        if not isinstance(exc, Exception):
            raise
        return _mcp_test_failure(
            exc,
            stderr=client.stderr_logs(),
            sensitive_values=[*server.env.values(), *server.headers.values()],
        )
    tools: list[dict[str, Any]] = []
    details: list[str] = []
    skipped_tools: list[dict[str, str]] = []
    for discovered_tool in discovered_tools:
        tool_name = str(
            discovered_tool.get("name")
            if isinstance(discovered_tool, dict)
            else getattr(discovered_tool, "name", "")
        ).strip() or "unknown"
        try:
            tool = MCPDiscoveredTool.model_validate(discovered_tool)
            tool_name = tool.name
            prepared = prepare_mcp_tool(server, tool)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            skipped_tools.append({"name": tool_name, "message": message})
            details.append(f"{tool_name}: {message}")
            continue
        tools.append(
            {
                "tool_id": prepared.spec.id,
                "name": humanize_identifier(tool.name) or tool.name,
                "description": prepared.spec.description,
                "risk_level": prepared.spec.risk_level,
                "permission_scope": prepared.spec.permission_scope,
                "permission_tags": prepared.spec.permission_tags,
                "concurrent": prepared.spec.concurrent,
            }
        )
        for repair in prepared.repairs:
            details.append(
                f"{tool.name}: normalized {repair['schema']} schema at "
                f"{repair['path']} from {repair['original']!r}"
            )
    if discovered_tools and not tools:
        return {
            "status": "failed",
            "message": "The MCP server connected, but none of its tools have usable schemas.",
            "preflight": preflight,
            "tool_count": 0,
            "tools": [],
            "skipped_tool_count": len(skipped_tools),
            "skipped_tools": skipped_tools,
            "details": details,
        }
    skipped_count = len(skipped_tools)
    message = f"Discovered {len(tools)} usable tools."
    if skipped_count:
        message = f"{message} Skipped {skipped_count} tool(s) with incompatible schemas."
    return {
        "status": "ok",
        "message": message,
        "preflight": preflight,
        "tool_count": len(tools),
        "tools": tools,
        "skipped_tool_count": skipped_count,
        "skipped_tools": skipped_tools,
        "details": details,
    }


def _mcp_test_failure(
    exc: BaseException,
    *,
    stderr: list[str],
    sensitive_values: list[str],
) -> dict[str, Any]:
    details = [_redact_mcp_test_text(message, sensitive_values) for message in exception_leaf_messages(exc)]
    stderr_lines = [
        _redact_mcp_test_text(line.strip(), sensitive_values)
        for line in stderr
        if line.strip()
    ]
    primary_message = stderr_lines[-1] if stderr_lines else details[0]
    return {
        "status": "failed",
        "message": primary_message,
        "error_type": type(exc).__name__,
        "details": details,
        "stderr": stderr_lines,
        "tool_count": 0,
        "tools": [],
    }


def _redact_mcp_test_text(value: str, sensitive_values: list[str]) -> str:
    redacted = value
    secrets = sorted({secret for secret in sensitive_values if secret}, key=len, reverse=True)
    for secret in secrets:
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _install_mcp_servers(
    extension_root: Path,
    payload: dict[str, Any],
    *,
    summary: Callable[[], dict[str, Any]],
    package: LoadedAgentPackage | None,
    system_owner: SystemAgentExtensionOwner | None,
    operation: MCPRuntimeOperation | None,
) -> ExtensionManageResult:
    raw_servers = payload.get("servers")
    if not isinstance(raw_servers, list) or not raw_servers:
        raise ValueError("install_mcp requires a non-empty servers array")
    servers = [
        _mcp_server_for_upsert(
            extension_root,
            {"server": raw},
            package=package,
            system_owner=system_owner,
        )
        for raw in raw_servers
        if isinstance(raw, dict)
    ]
    if len(servers) != len(raw_servers):
        raise ValueError("install_mcp servers must contain objects")
    if len({server.server_id for server in servers}) != len(servers):
        raise ValueError("install_mcp server_id values must be unique")
    tests: list[dict[str, Any]] = []
    for server in servers:
        test = {
            "server_id": server.server_id,
            **_test_mcp_server(server.model_copy(update={"enabled": True}), operation=operation),
        }
        tests.append(test)
        if test.get("status") == "cancelled":
            return ExtensionManageResult(
                {
                    "install": {
                        "status": "cancelled",
                        "message": "MCP server validation was stopped; no configuration was saved.",
                        "tests": tests,
                    },
                    **summary(),
                }
            )
    failed = [test for test in tests if test.get("status") != "ok"]
    if failed:
        return ExtensionManageResult(
            {
                "install": {
                    "status": "failed",
                    "message": f"{len(failed)} MCP server(s) failed validation; no configuration was saved.",
                    "tests": tests,
                },
                **summary(),
            }
        )
    _save_mcp_servers(extension_root, servers)
    for server, test in zip(servers, tests, strict=True):
        replace_registered_mcp_tool_catalog(server.server_id, list(test.get("tools") or []))
    return ExtensionManageResult(
        {
            "install": {
                "status": "ok",
                "message": f"Installed {len(servers)} MCP server(s).",
                "tests": tests,
            },
            **summary(),
        },
        changed=True,
    )


def _mcp_server_preflight(server: MCPServerConfig) -> dict[str, Any]:
    if server.transport == "stdio":
        command = str(server.command or "").strip()
        if not command:
            return {"status": "failed", "message": f"MCP stdio server requires command: {server.server_id}"}
        resolved = shutil.which(command)
        if resolved is None and ("/" in command or "\\" in command):
            candidate = Path(command).expanduser()
            resolved = str(candidate.resolve()) if candidate.is_file() else None
        if resolved is None:
            return {"status": "failed", "message": f"MCP command is not available: {command}"}
        runner = Path(command).name
        return {
            "status": "ok",
            "message": f"Command is available: {resolved}",
            "transport": "stdio",
            "strategy": "package_runner" if runner in {"npx", "uvx", "pipx", "bunx"} else "local_command",
            "resolved_command": resolved,
        }
    if server.transport not in {"streamable_http", "sse"}:
        return {"status": "failed", "message": f"Unsupported MCP transport: {server.transport}"}
    parsed = urlparse(str(server.url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"status": "failed", "message": f"MCP {server.transport} server requires a valid HTTP(S) URL"}
    return {
        "status": "ok",
        "message": f"Remote endpoint is configured: {parsed.scheme}://{parsed.netloc}",
        "transport": server.transport,
        "strategy": "remote_endpoint",
    }


def _required_config_id(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_identifier(value: Any) -> str | None:
    text = str(value or "").strip()
    return _config_identifier(text, fallback="") if text else None


def _config_identifier(value: str, *, fallback: str) -> str:
    raw = value.strip() or fallback.strip()
    identifier = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")
    if not identifier:
        identifier = "item"
    if identifier[0].isdigit():
        identifier = f"item_{identifier}"
    return identifier[:64]


def _parse_args(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return shlex.split(text)


def _parse_env(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items() if str(key).strip()}
    env: dict[str, str] = {}
    for line in str(value or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, item = stripped.split("=", 1)
        key = key.strip()
        if key:
            env[key] = item.strip()
    return env


def _mcp_server_summary(payload: dict[str, Any]) -> str:
    transport = str(payload.get("transport") or "unknown")
    command = str(payload.get("command") or "").strip()
    url = str(payload.get("url") or "").strip()
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    package = str(source.get("package") or "").strip()
    if package:
        return f"{transport} connection from {package}"
    if command:
        return f"{transport} connection via {command}"
    if url:
        return f"{transport} connection to {url}"
    return f"{transport} connection"


def _skill_summary(payload: dict[str, Any]) -> str:
    source = str(payload.get("source") or "local")
    path = str(payload.get("path") or "").strip()
    if path:
        return f"{source} skill at {path}"
    return f"{source} skill"


def _skill_metadata_for_public_view(payload: dict[str, Any]) -> dict[str, Any]:
    path = str(payload.get("path") or "").strip()
    if not path:
        return {}
    source = str(payload.get("source") or "local")
    try:
        skill = parse_skill_directory(
            path,
            allow_directory_name_mismatch=source in {"skillhub", "distribution"},
            allow_missing_frontmatter=source in {"skillhub", "distribution"},
            fallback_name=str(payload.get("skill_id") or Path(path).name),
        )
    except Exception:
        return {}
    return {
        "name": skill.metadata.name,
        "description": skill.metadata.description,
        "resource_count": len(skill.resources),
        "script_count": len(skill.scripts),
    }
