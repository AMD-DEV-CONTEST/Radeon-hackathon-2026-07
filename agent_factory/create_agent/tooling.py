from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import BaseTool

from agent_factory.create_agent.authoring_tool import (
    CREATE_AGENT_AUTHORING_TOOL_ID,
    build_create_agent_authoring_tool_spec,
)
from agent_factory.create_agent.capability_inventory import build_capability_inventory
from agent_factory.create_agent.control_tool import (
    CREATE_AGENT_CONTROL_TOOL_ID,
    CREATE_AGENT_WORKSPACE_RESOURCE,
    build_create_agent_control_tool_spec,
)
from agent_factory.create_agent.models import (
    ACTION_FILE,
    KNOWLEDGE_SOURCES_FILE,
    PUBLISH_FILE,
    PUBLISH_DECISION_FILE,
    SKILL_GATEWAY_STATE_FILE,
    SYSTEM_STATE_FILE,
    TASK_ANALYSIS_FILE,
    TOOL_PROBE_FILE,
    VALIDATION_FILE,
    VALIDATION_STATE_FILE,
)
from agent_factory.create_agent.model_pool_tool import (
    CREATE_AGENT_MODEL_POOL_TOOL_ID,
    build_model_pool_select_tool_spec,
)
from agent_factory.create_agent.publish_tool import CREATE_AGENT_PACKAGE_REGISTRY_RESOURCE
from agent_factory.create_agent.probe_tool import CREATE_AGENT_PROBE_TOOL_ID, build_create_agent_probe_tool_spec
from agent_factory.create_agent.resource_tool import (
    CREATE_AGENT_RESOURCE_TOOL_ID,
    build_create_agent_resource_tool_spec,
)
from agent_factory.create_agent.skillhub_runtime import wrap_create_agent_skillhub_runtime
from agent_factory.create_agent.stage_context import CREATE_AGENT_STAGE_CONTEXT_RESOURCE, stage_context_payload
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.create_agent.stage_tool import CREATE_AGENT_STAGE_TOOL_ID, build_create_agent_stage_tool_spec
from agent_factory.create_agent.validate_tool import CREATE_AGENT_VALIDATE_TOOL_ID, build_create_agent_validate_tool_spec
from agent_factory.tooling.skillhub.constants import SKILLHUB_RUNTIME_RESOURCE
from agent_factory.tooling.builtins.resource_set.resource_set import RESOURCE_SET_STORE_KEY, ResourceSetStore
from agent_factory.tooling.builtins.tool_output.specs import get_tool_output_tool_specs
from agent_factory.tooling.approval_policy import (
    default_tool_approval_policy,
    load_tool_approval_policy_file,
    merge_tool_approval_policy,
)
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.factory_extensions import (
    FactoryExtensionLoadReport,
    FactoryExtensionManager,
    default_system_agent_extension_root,
)
from agent_factory.tooling.extension_registry import (
    default_extension_registry_root,
    selected_registry_configs,
)
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import (
    BuiltinToolProvider,
    SkillProvider,
    ToolProviderContext,
    ToolProviderResult,
)
from agent_factory.tooling.registry import ToolRegistry
from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR
from agent_factory.tooling.skills import (
    SKILL_TOOL_ID,
    SkillRegistry,
    build_skill_tool_spec,
    parse_skill_directory,
)
from agent_factory.tooling.skills.schema import SkillGatewayState
from agent_factory.tooling.skills.skill_tool import SKILL_GATEWAY_STATE_RESOURCE_KEY


CREATE_AGENT_BUILTIN_TOOL_IDS = {
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    "ls",
    "skillhub",
    "tool_output",
    "resource_set",
}
CREATE_AGENT_ASSIST_TOOL_IDS = {
    "read",
    "glob",
    "grep",
    "ls",
    "tool_output",
}

CREATE_AGENT_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"
EVOLUTION_SKILLS_ROOT = Path(__file__).resolve().parents[1] / "evolution" / "skills"


@dataclass(frozen=True, slots=True)
class CreateAgentToolEnvironment:
    tools: list[BaseTool]
    tool_ids: list[str]
    system_tool_ids: list[str]
    extension_report: dict[str, Any]
    capability_inventory: dict[str, Any]


class CreateAgentToolEnvironmentBuilder:
    def __init__(self, *, extension_manager: FactoryExtensionManager | None = None) -> None:
        self.extension_manager = extension_manager

    def build(
        self,
        *,
        workspace_root: str | Path,
        mode: Literal["manufacture", "assist", "evolution"] = "manufacture",
        evolution_target_plan: dict[str, Any] | None = None,
    ) -> CreateAgentToolEnvironment:
        workspace = Path(workspace_root).expanduser().resolve()
        create_agent_workspace = CreateAgentWorkspace(workspace)
        system_agent_owner = "evolve_agent" if mode == "evolution" else "create_agent"
        extension_manager = self.extension_manager or FactoryExtensionManager(
            extension_root=default_system_agent_extension_root(system_agent_owner),
            include_builtin_extension_root=True,
        )
        factory_extension_root = extension_manager.extension_root
        package_extension_root = workspace / "extensions"
        provider_resources = {
            "builtin_workspace_root": str(workspace),
            "builtin_allow_external_paths": False,
        }
        builtin_context = ToolProviderContext(
            package_root=workspace,
            extension_root=default_extension_registry_root(),
            resources=provider_resources,
        )
        extension_context = ToolProviderContext(
            package_root=workspace,
            extension_root=factory_extension_root,
            resources=provider_resources,
        )
        authoring_mode = mode in {"manufacture", "evolution"}
        builtin_tool_ids = CREATE_AGENT_BUILTIN_TOOL_IDS if authoring_mode else CREATE_AGENT_ASSIST_TOOL_IDS
        builtin_result = BuiltinToolProvider(tool_ids=builtin_tool_ids).discover(builtin_context)
        if authoring_mode:
            extension_result, extension_report = extension_manager.discover(context=extension_context)
            registry_result, _registry_report = extension_manager.discover_registry(
                context=extension_context
            )
            workspace_skill_result = _discover_workspace_skills(package_extension_root, context=builtin_context)
            _append_workspace_skill_report(extension_report, package_extension_root, workspace_skill_result)
        else:
            extension_result = ToolProviderResult()
            registry_result = ToolProviderResult()
            extension_report = FactoryExtensionLoadReport(extension_root=str(factory_extension_root))
            workspace_skill_result = ToolProviderResult()
        provider_result = builtin_result.merge(extension_result) if authoring_mode else builtin_result
        runtime_resources = {
            **builtin_result.runtime_resources,
            **(extension_result.runtime_resources if authoring_mode else {}),
            CREATE_AGENT_WORKSPACE_RESOURCE: {"root": str(workspace)},
            CREATE_AGENT_STAGE_CONTEXT_RESOURCE: stage_context_payload(workspace),
            TOOL_OUTPUT_STORE_RESOURCE: ToolOutputStore(workspace / ".factory" / "tool_outputs"),
        }
        if mode == "evolution" and evolution_target_plan is not None:
            runtime_resources["evolution_target_plan"] = evolution_target_plan
        if authoring_mode:
            runtime_resources[RESOURCE_SET_STORE_KEY] = ResourceSetStore()
            runtime_resources[CREATE_AGENT_PACKAGE_REGISTRY_RESOURCE] = str(factory_artifact_path("packages"))
        factory_skill_payload = extension_result.runtime_resources.get("skills")
        workspace_skill_payload = workspace_skill_result.runtime_resources.get("skills")
        if authoring_mode:
            def refresh_skill_resource() -> None:
                _refresh_create_agent_skill_resource(
                    runtime_resources=runtime_resources,
                    factory_skill_payload=factory_skill_payload,
                    package_extension_root=package_extension_root,
                    package_context=builtin_context,
                    gateway_state_path=create_agent_workspace.skill_gateway_state_path,
                    mode=mode,
                )
        else:
            refresh_skill_resource = None
        if authoring_mode and SKILLHUB_RUNTIME_RESOURCE in runtime_resources:
            runtime_resources[SKILLHUB_RUNTIME_RESOURCE] = wrap_create_agent_skillhub_runtime(
                runtime_resources[SKILLHUB_RUNTIME_RESOURCE],
                package_root=workspace,
                on_skill_config_changed=refresh_skill_resource,
            )
        filesystem_resource = runtime_resources.get("filesystem")
        if isinstance(filesystem_resource, dict) and authoring_mode:
            filesystem_resource[CREATE_AGENT_STAGE_CONTEXT_RESOURCE] = runtime_resources[CREATE_AGENT_STAGE_CONTEXT_RESOURCE]
            read_only_paths = filesystem_resource.setdefault("read_only_paths", [])
            if isinstance(read_only_paths, list):
                read_only_paths.append(f".factory/{ATTACHMENT_INPUT_DIR}")
            filesystem_resource["protected_write_paths"] = [
                ACTION_FILE,
                KNOWLEDGE_SOURCES_FILE,
                SYSTEM_STATE_FILE,
                VALIDATION_FILE,
                VALIDATION_STATE_FILE,
                TOOL_PROBE_FILE,
                PUBLISH_FILE,
                PUBLISH_DECISION_FILE,
                SKILL_GATEWAY_STATE_FILE,
                TASK_ANALYSIS_FILE,
                ".factory/manufacturing_trace.json",
                ".factory/probe_jobs",
                ".factory/tool_outputs",
                ".agent_runtime",
            ]
            filesystem_resource["managed_paths"] = {
                ACTION_FILE: {
                    "read_tool": CREATE_AGENT_CONTROL_TOOL_ID,
                    "write_tool": CREATE_AGENT_CONTROL_TOOL_ID,
                },
                SYSTEM_STATE_FILE: {
                    "read_tool": CREATE_AGENT_STAGE_TOOL_ID,
                    "write_tool": CREATE_AGENT_STAGE_TOOL_ID,
                },
                TASK_ANALYSIS_FILE: {
                    "read_tool": CREATE_AGENT_STAGE_TOOL_ID,
                    "write_tool": "create-agent task analysis",
                },
                KNOWLEDGE_SOURCES_FILE: {
                    "read_tool": CREATE_AGENT_AUTHORING_TOOL_ID,
                    "write_tool": CREATE_AGENT_AUTHORING_TOOL_ID,
                },
            }
            filesystem_resource["managed_write_paths"] = {
                "agent_package.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "assembly_spec.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/tools.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/dependencies.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/resources.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/scheduler_seed.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/context.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/model.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/scheduler.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "extensions/extension_bindings.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "tools": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "knowledge": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
            }
        if authoring_mode:
            skill_registry = _create_agent_skill_registry(
                [factory_skill_payload, workspace_skill_payload],
                gateway_state=_load_skill_gateway_state(create_agent_workspace.skill_gateway_state_path),
                mode=mode,
            )
            if skill_registry.list_metadata():
                runtime_resources["skills"] = skill_registry.to_resource_payload()
                runtime_resources[SKILL_GATEWAY_STATE_RESOURCE_KEY] = str(create_agent_workspace.skill_gateway_state_path)
                provider_result.system_tool_ids = sorted(set([*provider_result.system_tool_ids, SKILL_TOOL_ID]))
                skill_specs = [
                    build_skill_tool_spec(
                        persist_gateway_state=True,
                        stage_context_resource=CREATE_AGENT_STAGE_CONTEXT_RESOURCE,
                    )
                ]
            else:
                skill_specs = []
            create_agent_tool_ids = [
                CREATE_AGENT_AUTHORING_TOOL_ID,
                CREATE_AGENT_CONTROL_TOOL_ID,
                CREATE_AGENT_MODEL_POOL_TOOL_ID,
                CREATE_AGENT_PROBE_TOOL_ID,
                CREATE_AGENT_RESOURCE_TOOL_ID,
                CREATE_AGENT_VALIDATE_TOOL_ID,
                CREATE_AGENT_STAGE_TOOL_ID,
            ]
            provider_result.system_tool_ids = sorted(
                set(
                    [
                        *provider_result.system_tool_ids,
                        *create_agent_tool_ids,
                    ]
                )
            )
            extra_specs = [
                build_create_agent_control_tool_spec(),
                build_model_pool_select_tool_spec(),
                build_create_agent_authoring_tool_spec(),
                build_create_agent_probe_tool_spec(),
                build_create_agent_resource_tool_spec(),
                build_create_agent_validate_tool_spec(),
                build_create_agent_stage_tool_spec(),
                *skill_specs,
            ]
        else:
            extra_specs = []
        specs = _stable_specs(
            _unique_specs(
                provider_result,
                extra_specs=extra_specs,
            )
        )
        extension_specs = _stable_specs(registry_result.tool_specs) if authoring_mode else []
        capability_inventory = build_capability_inventory(
            manufacturing_specs=specs,
            extension_specs=extension_specs,
        )
        registry = ToolRegistry(specs)
        approval_policy = merge_tool_approval_policy(
            default_tool_approval_policy(),
            load_tool_approval_policy_file(factory_extension_root / "tool_permissions.json"),
        )
        compiler = ToolCompiler(
            package_root=workspace,
            resources=runtime_resources,
            approval_policy=approval_policy,
            allowed_python_roots=[factory_extension_root, package_extension_root],
            mcp_clients=extension_manager.mcp_tool_clients() if authoring_mode else {},
        )
        tools = _stable_tools(compiler.compile_many(registry.all()))
        return CreateAgentToolEnvironment(
            tools=tools,
            tool_ids=[tool.name for tool in tools],
            system_tool_ids=sorted(set(provider_result.system_tool_ids)),
            extension_report=extension_report.model_dump(mode="json"),
            capability_inventory=capability_inventory.model_dump(mode="json"),
        )


def _stable_specs(specs: list[Any]) -> list[Any]:
    return sorted(specs, key=lambda spec: str(spec.id))


def _stable_tools(tools: list[BaseTool]) -> list[BaseTool]:
    return sorted(tools, key=lambda tool: str(tool.name))


def _unique_specs(result: ToolProviderResult, *, extra_specs=()):
    specs = []
    seen = set()
    for spec in [
        *(spec for spec in result.tool_specs if spec.id != SKILL_TOOL_ID),
        *get_tool_output_tool_specs(),
        *extra_specs,
    ]:
        if spec.id in seen:
            continue
        seen.add(spec.id)
        specs.append(spec)
    return specs


def _discover_workspace_skills(extension_root: Path, *, context: ToolProviderContext) -> ToolProviderResult:
    _mcp, config, _bindings = selected_registry_configs([extension_root])
    if not config.skills:
        return ToolProviderResult()
    return SkillProvider(config=config).discover(context)


def _append_workspace_skill_report(
    report: FactoryExtensionLoadReport,
    extension_root: Path,
    result: ToolProviderResult,
) -> None:
    enabled_skills_path = extension_root / "extension_bindings.json"
    if enabled_skills_path.is_file():
        report.enabled_skills_path = str(enabled_skills_path)
        report.enabled_skills_paths = _unique_texts([*report.enabled_skills_paths, str(enabled_skills_path)])
    report.tool_ids = _unique_texts([*report.tool_ids, *(spec.id for spec in result.tool_specs)])
    report.system_tool_ids = _unique_texts([*report.system_tool_ids, *result.system_tool_ids])
    report.runtime_dependency_ids = _unique_texts(
        [*report.runtime_dependency_ids, *(dependency.dependency_id for dependency in result.runtime_dependencies)]
    )
    report.diagnostics.extend(diagnostic.model_dump(mode="json") for diagnostic in result.diagnostics)


def _create_agent_skill_registry(
    existing_payload: Any,
    *,
    gateway_state: SkillGatewayState | None = None,
    mode: Literal["manufacture", "assist", "evolution"] = "manufacture",
) -> SkillRegistry:
    registry = SkillRegistry()
    for payload in _skill_payloads(existing_payload):
        if not isinstance(payload, dict):
            continue
        for skill in SkillRegistry.from_resource_payload(payload).packages():
            registry.register(skill)
    if gateway_state is not None:
        registry.gateway_state = gateway_state
    roots = [CREATE_AGENT_SKILLS_ROOT, EVOLUTION_SKILLS_ROOT] if mode == "evolution" else [CREATE_AGENT_SKILLS_ROOT]
    for root in roots:
        if root.is_dir():
            _register_skill_root(registry, root)
    return registry


def _refresh_create_agent_skill_resource(
    *,
    runtime_resources: dict[str, Any],
    factory_skill_payload: Any,
    package_extension_root: Path,
    package_context: ToolProviderContext,
    gateway_state_path: Path,
    mode: Literal["manufacture", "assist", "evolution"],
) -> None:
    workspace_skill_result = _discover_workspace_skills(package_extension_root, context=package_context)
    registry = _create_agent_skill_registry(
        [factory_skill_payload, workspace_skill_result.runtime_resources.get("skills")],
        gateway_state=_load_skill_gateway_state(gateway_state_path),
        mode=mode,
    )
    if registry.list_metadata():
        runtime_resources["skills"] = registry.to_resource_payload()
    else:
        runtime_resources.pop("skills", None)


def _skill_payloads(payload: Any) -> list[Any]:
    if isinstance(payload, (list, tuple)):
        return list(payload)
    return [payload]


def _register_skill_root(registry: SkillRegistry, root: Path) -> None:
    for child in sorted(item for item in root.iterdir() if item.is_dir()):
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        registry.register(parse_skill_directory(child))


def _load_skill_gateway_state(path: Path) -> SkillGatewayState | None:
    if not path.exists():
        return None
    try:
        return SkillGatewayState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        # Invalid skill gateway state is non-fatal during tool environment setup.
        # The validator will detect and report the broken JSON so the LLM can repair it.
        return None


def _unique_texts(values: list[Any]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items
