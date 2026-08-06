from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.errors import GraphInterrupt

from agent_factory.artifact_system import ArtifactStore, ReportStore
from agent_factory.context_system.runtime import ContextSystemRuntime
from agent_factory.context_system.sources import default_context_sources
from agent_factory.knowledge_system import KnowledgeRuntimeConfig, build_knowledge_runtime
from agent_factory.memory_system import default_agent_runtime
from agent_factory.memory_system.background import MemoryBackgroundWorker
from agent_factory.memory_system.migration import migrate_legacy_sqlite_memory
from agent_factory.memory_system.scopes import local_memory_user_id, memory_migration_log_path
from agent_factory.memory_system.store_index import build_memory_store_index
from agent_factory.model_pool import (
    resolve_chat_model_binding,
    resolve_image_generation_binding,
)
from agent_factory.runtime_contracts.builder import RuntimeBuildContext
from agent_factory.runtime_contracts.contribution import RuntimeContribution
from agent_factory.runtime_contracts.memory_config import memory_system_config_from_context
from agent_factory.runtime_contracts.paths import (
    package_runtime_path_text,
    resolve_package_runtime_path,
)
from agent_factory.runtime_contracts.schema import (
    ArtifactContract,
    ContextContract,
    DependenciesContract,
    ModelContract,
    NodeProviderContract,
    ResourcesContract,
    SchedulerContract,
    SchedulerSeedContract,
    ToolsContract,
    TraceContract,
)
from agent_factory.runtime_kernel.adapters import InMemoryToolRegistry, LangChainModelServiceAdapter
from agent_factory.runtime_kernel.extensions.manager import AgentInstanceExtensionManager
from agent_factory.runtime_kernel.prompt_fragments import RUNTIME_PROMPT_FRAGMENTS_SESSION_KEY
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.runtime_kernel.node_providers import NodeProviderRegistry
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphCheckpointerFactory,
    LangGraphStoreConfig,
    LangGraphStoreFactory,
    migrate_legacy_instance_checkpoints,
)
from agent_factory.runtime_kernel.types import ToolExecutionResult
from agent_factory.runtime_kernel.wrappers.system_context import CONTEXT_PREPARE_SYSTEM_WRAPPER_ID
from agent_factory.runtime_kernel.wrappers.system_knowledge import KNOWLEDGE_GUIDANCE_SYSTEM_WRAPPER_ID
from agent_factory.scheduler_system import SchedulerExecutor, SchedulerRuntime, SchedulerWorker, SQLiteSchedulerStore
from agent_factory.tooling.approval_policy import (
    ToolApprovalPolicyConfig,
    load_tool_approval_policy_file,
    merge_tool_approval_policy,
    resolve_tool_approval_policy,
)
from agent_factory.tooling.builtins.model_tools import MODEL_TOOL_RUNTIME_RESOURCE, get_model_tool_specs
from agent_factory.tooling.builtins.tool_output.specs import get_tool_output_tool_specs
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import BuiltinToolProvider, PackageToolProvider, ToolProviderContext
from agent_factory.tooling.registry import ToolRegistry
from agent_factory.tooling.runtime_settings import apply_tool_runtime_settings, load_tool_runtime_settings
from agent_factory.trace_system import JSONLTraceStore, TraceDiagnostics, TraceProjector, TraceReader, TraceRecorder
from agent_factory.trace_system.runtime_log import RuntimeLogStore


def build_session_runtime(context: RuntimeBuildContext) -> RuntimeContribution:
    runtime_root = context.runtime_root or context.package_root / ".agent_runtime"
    session_root = runtime_root / "sessions"
    checkpoint_path = runtime_root / "checkpoints" / "agent.sqlite"
    migrate_legacy_instance_checkpoints(checkpoint_path)
    checkpointer = LangGraphCheckpointerFactory().build(
        LangGraphCheckpointerConfig(backend="sqlite", path=checkpoint_path)
    ).saver
    return RuntimeContribution(
        services={"checkpointer": checkpointer},
        session_config={
            "session_root": str(session_root),
            "checkpointer_backend": "sqlite",
            "checkpoint_path": str(checkpoint_path),
        },
    )


def build_knowledge_runtime_infrastructure(context: RuntimeBuildContext) -> RuntimeContribution:
    runtime_root = context.runtime_root or context.package_root / ".agent_runtime"
    knowledge_root = runtime_root / "knowledge"
    defaults = KnowledgeRuntimeConfig()
    config = defaults.model_copy(
        update={
            "root": str(knowledge_root),
            "catalog_path": str(knowledge_root / "catalog" / "knowledge.sqlite"),
            "rag_store": defaults.rag_store.model_copy(
                update={"path": str(knowledge_root / "catalog" / "knowledge_store.sqlite")}
            ),
        }
    )
    assembly = build_knowledge_runtime(
        config=config,
        owner_type="agent",
        owner_id=context.package.assembly_spec.agent.id,
    )
    return RuntimeContribution(
        services={"knowledge_runtime": assembly.runtime},
        system_wrappers=[KNOWLEDGE_GUIDANCE_SYSTEM_WRAPPER_ID],
        tool_runtime_resources={"knowledge_runtime": assembly.runtime},
        background_workers=[assembly.ingestion_worker],
    )


class ToolsContractBuilder:
    contract_type = "tools"
    contract_version = "tools_contract.v0"

    def build(self, contract: ToolsContract, context: RuntimeBuildContext) -> RuntimeContribution:
        config = contract.config
        specs = []
        runtime_resources: dict[str, Any] = {}
        tool_runtime_resources = dict(context.tool_runtime_resources)
        if context.runtime_root is not None:
            runtime_root = context.runtime_root
        else:
            runtime_root = context.package_root / ".agent_runtime"
        tool_runtime_resources.setdefault("runtime_root", str(runtime_root))
        tool_runtime_resources.setdefault("artifacts_root", str(runtime_root / "artifacts"))
        tool_runtime_resources.setdefault("workdir_root", config.builtin_workspace_root)
        tool_runtime_resources.setdefault("package_root", str(context.package_root))
        tool_runtime_resources.setdefault("workspace_root", str(context.package_root))
        mcp_clients = {}
        system_tool_ids: set[str] = set()
        prompt_fragments: list[dict[str, Any]] = []
        instance_extension_root = context.instance_extension_root or resolve_package_runtime_path(
            context,
            config.instance_extension_root,
            field_path="tools.config.instance_extension_root",
        )
        tool_runtime_resources.setdefault(
            TOOL_OUTPUT_STORE_RESOURCE,
            ToolOutputStore(_tool_output_root(context=context, instance_extension_root=instance_extension_root)),
        )
        provider_context = ToolProviderContext(
            package_root=context.package_root,
            extension_root=instance_extension_root,
            resources=context.resources,
        )
        if config.builtin_tools_enabled:
            builtin_result = BuiltinToolProvider(tool_ids=config.builtin_tool_ids).discover(
                ToolProviderContext(
                    package_root=context.package_root,
                    extension_root=instance_extension_root,
                    resources={
                        "builtin_workspace_root": config.builtin_workspace_root,
                        "builtin_allow_external_paths": config.builtin_allow_external_paths,
                    },
                )
            )
            if "scheduler_runtime" not in tool_runtime_resources:
                builtin_result.tool_specs = [spec for spec in builtin_result.tool_specs if spec.id != "scheduler"]
                builtin_result.system_tool_ids = [tool_id for tool_id in builtin_result.system_tool_ids if tool_id != "scheduler"]
            if "knowledge_runtime" not in tool_runtime_resources:
                builtin_result.tool_specs = [spec for spec in builtin_result.tool_specs if spec.id != "knowledge"]
                builtin_result.system_tool_ids = [tool_id for tool_id in builtin_result.system_tool_ids if tool_id != "knowledge"]
            specs.extend(builtin_result.tool_specs)
            system_tool_ids.update(builtin_result.system_tool_ids)
            runtime_resources.update(builtin_result.runtime_resources)
            prompt_fragments.extend(
                fragment.model_dump(mode="json")
                for fragment in builtin_result.prompt_fragments
            )
        if config.package_tools_enabled:
            package_result = PackageToolProvider().discover(provider_context)
            specs.extend(package_result.tool_specs)
            system_tool_ids.update(package_result.system_tool_ids)
            runtime_resources.update(package_result.runtime_resources)
            prompt_fragments.extend(
                fragment.model_dump(mode="json")
                for fragment in package_result.prompt_fragments
            )
        if config.instance_extensions_enabled:
            manager = AgentInstanceExtensionManager(
                extension_root=instance_extension_root,
                inherit_builtin_extensions=_inherits_builtin_agent_extensions(context.package),
                inherited_extension_roots=_package_extension_roots(context),
            )
            extension_result, _ = manager.discover(context=provider_context)
            specs.extend(extension_result.tool_specs)
            system_tool_ids.update(extension_result.system_tool_ids)
            runtime_resources.update(extension_result.runtime_resources)
            prompt_fragments.extend(
                fragment.model_dump(mode="json")
                for fragment in extension_result.prompt_fragments
            )
            mcp_clients = manager.mcp_tool_clients()
        if TOOL_OUTPUT_STORE_RESOURCE in tool_runtime_resources and not any(spec.id == "tool_output" for spec in specs):
            tool_output_spec = get_tool_output_tool_specs()[0]
            specs.append(tool_output_spec)
            system_tool_ids.add(tool_output_spec.id)
        model_tool_runtime = tool_runtime_resources.get(MODEL_TOOL_RUNTIME_RESOURCE)
        if isinstance(model_tool_runtime, dict) and model_tool_runtime:
            model_tool_specs = get_model_tool_specs(model_tool_runtime)
            specs.extend(model_tool_specs)
            system_tool_ids.update(spec.id for spec in model_tool_specs)
        specs = apply_tool_runtime_settings(specs, load_tool_runtime_settings(instance_extension_root))
        registry = ToolRegistry(specs)
        approval_policy = merge_tool_approval_policy(
            resolve_tool_approval_policy(config.approval_policy),
            _instance_tool_approval_policy(instance_extension_root),
        )
        compiler = ToolCompiler(
            package_root=context.package_root,
            resources=_merge_tool_resources(
                serializable_resources=context.resources,
                provider_runtime_resources=runtime_resources,
                tool_runtime_resources=tool_runtime_resources,
            ),
            approval_policy=approval_policy,
            allowed_python_roots=[instance_extension_root],
            mcp_clients=mcp_clients,
        )
        compiled_tools = {tool.name: tool for tool in compiler.compile_many(registry.all())}
        runtime_registry = InMemoryToolRegistry(
            {
                tool_id: _runtime_tool_executor(tool_id, tool)
                for tool_id, tool in compiled_tools.items()
            },
            model_tools=compiled_tools,
            system_tool_ids=system_tool_ids,
        )
        session_config = {
            "builtin_workspace_root": config.builtin_workspace_root,
            "builtin_allow_external_paths": config.builtin_allow_external_paths,
        }
        if prompt_fragments:
            session_config[RUNTIME_PROMPT_FRAGMENTS_SESSION_KEY] = prompt_fragments
        return RuntimeContribution(
            services={"tool_registry": runtime_registry},
            session_config=session_config,
        )


def _memory_runtime_contribution(
    contract: ContextContract,
    context: RuntimeBuildContext,
) -> RuntimeContribution:
    config = memory_system_config_from_context(contract.config, context)
    if not config.enabled:
        return RuntimeContribution(
            services={
                "memory_system": default_agent_runtime(
                    agent_id=context.package.assembly_spec.agent.id,
                    config=config,
                    store=None,
                ),
            }
        )
    store_config = LangGraphStoreConfig(
        backend=config.store.backend,
        path=Path(config.store.path),
        setup=config.store.setup,
        index=build_memory_store_index(config),
    )
    store = LangGraphStoreFactory().build(store_config).store
    runtime_root = context.runtime_root or context.package_root / ".agent_runtime"
    if config.store.backend != "memory":
        migrate_legacy_sqlite_memory(
            source_path=runtime_root / "memory" / "agent.sqlite",
            target_store=store,
            agent_id=context.package.assembly_spec.agent.id,
            session_root=runtime_root / "sessions",
            log_path=memory_migration_log_path(runtime_root),
        )
    runtime = default_agent_runtime(
        agent_id=context.package.assembly_spec.agent.id,
        config=config,
        store=store,
        user_id=local_memory_user_id(),
    )
    background_workers: list[Any] = []
    if config.write_enabled:
        worker = MemoryBackgroundWorker(store=store, config=config)
        runtime.writer = worker
        background_workers.append(worker)
    return RuntimeContribution(
        services={"memory_store": store, "memory_system": runtime},
        background_workers=background_workers,
    )


class ContextContractBuilder:
    contract_type = "context"
    contract_version = "context_contract.v1"

    def build(self, contract: ContextContract, context: RuntimeBuildContext) -> RuntimeContribution:
        sources = default_context_sources()
        memory = _memory_runtime_contribution(contract, context)
        return RuntimeContribution(
            services={
                **memory.services,
                "context_system": ContextSystemRuntime(config=contract.config, sources=sources),
            },
            system_wrappers=[CONTEXT_PREPARE_SYSTEM_WRAPPER_ID],
            background_workers=memory.background_workers,
        )


class TraceContractBuilder:
    contract_type = "trace"
    contract_version = "trace_contract.v0"

    def build(self, contract: TraceContract, context: RuntimeBuildContext) -> RuntimeContribution:
        config = contract.config.model_copy(
            update={
                "root": package_runtime_path_text(context, contract.config.root, field_path="trace.config.root"),
            }
        )
        runtime = context.package.manifest.runtime or {}
        producer_type = "system_package" if runtime.get("system_package") else "agent_runtime"
        recorder = TraceRecorder(
            store=JSONLTraceStore(
                config.root,
                manifest_flush_record_interval=config.manifest_flush_record_interval,
            ),
            package_id=context.package.package_root.name,
            producer_type=producer_type,
            max_inline_payload_chars=config.max_inline_payload_chars,
            runtime_log_store=RuntimeLogStore(_runtime_log_path(context)),
        )
        reader = TraceReader(config.root)
        projector = TraceProjector(reader)
        diagnostics = TraceDiagnostics(projector)
        return RuntimeContribution(
            services={
                "trace_recorder": recorder,
                "trace_reader": reader,
                "trace_projector": projector,
                "trace_diagnostics": diagnostics,
            }
        )


class ModelContractBuilder:
    contract_type = "model"
    contract_version = "model_contract.v1"

    def build(self, contract: ModelContract, context: RuntimeBuildContext) -> RuntimeContribution:
        main_binding = contract.config.bindings.get("main")
        if main_binding is None:
            raise ValueError("model_contract.v1 requires config.bindings.main")
        resolved_profiles = {
            role: resolve_chat_model_binding(binding, role=role)
            for role, binding in contract.config.bindings.items()
            if binding.source != "runtime"
        }
        runtime_main_profile_required = main_binding.source == "runtime"
        if not runtime_main_profile_required and "main" not in resolved_profiles:
            raise ValueError("model_contract.v1 main binding could not be resolved")
        models_by_role = {
            role: (resolved.model, resolved.settings)
            for role, resolved in resolved_profiles.items()
        }
        model_tool_runtime = {}
        artifact_store = context.tool_runtime_resources.get("artifact_store")
        for tool_id, binding in contract.config.tool_bindings.items():
            if binding.capability in {"image_output", "image_edit"}:
                if not isinstance(artifact_store, ArtifactStore):
                    raise ValueError("image generation model tools require artifact_store from artifact contract")
                resolved_image = resolve_image_generation_binding(
                    binding,
                    artifact_store=artifact_store,
                )
                if resolved_image is None:
                    continue
                model_tool_runtime[tool_id] = {
                    "tool_id": tool_id,
                    "capability": binding.capability,
                    "description": binding.description,
                    "profile_id": resolved_image.profile_id,
                    "provider": resolved_image.settings.provider,
                    "model_name": resolved_image.settings.model,
                    "model_source": resolved_image.settings.source,
                    "image_generation_service": resolved_image.service,
                    "settings": resolved_image.settings,
                    "runtime_root": str(context.runtime_root or context.package_root / ".agent_runtime"),
                    "package_root": str(context.package_root),
                }
                continue
            resolved = resolve_chat_model_binding(binding, role=f"tool:{tool_id}")
            model_tool_runtime[tool_id] = {
                "tool_id": tool_id,
                "capability": binding.capability,
                "description": binding.description,
                "profile_id": resolved.profile_id,
                "provider": resolved.settings.provider,
                "model_name": resolved.settings.model or "",
                "model_source": resolved.settings.source,
                "model": resolved.model,
                "settings": resolved.settings,
                "runtime_root": str(context.runtime_root or context.package_root / ".agent_runtime"),
                "package_root": str(context.package_root),
            }
        return RuntimeContribution(
            services={
                "model_service": LangChainModelServiceAdapter(
                    role="main",
                    model=(resolved_profiles["main"].model if "main" in resolved_profiles else None),
                    settings=(resolved_profiles["main"].settings if "main" in resolved_profiles else None),
                    require_runtime_profile=runtime_main_profile_required,
                    runtime_profile_overrides=main_binding.overrides,
                ),
                "model_operation_service": ModelOperationService(
                    role="main",
                    models_by_role=models_by_role,
                    require_runtime_profile=runtime_main_profile_required,
                    runtime_profile_overrides=main_binding.overrides,
                ),
            },
            tool_runtime_resources=(
                {MODEL_TOOL_RUNTIME_RESOURCE: model_tool_runtime}
                if model_tool_runtime
                else {}
            ),
        )


def _runtime_log_path(context: RuntimeBuildContext) -> Path:
    runtime_root = context.runtime_root if context.runtime_root is not None else context.package_root / ".agent_runtime"
    return runtime_root / "logs" / "runtime_kernel.jsonl"


class NodeProviderContractBuilder:
    contract_type = "node_provider"
    contract_version = "node_provider_contract.v0"

    def __init__(self, *, provider_registry: NodeProviderRegistry | None = None) -> None:
        self.provider_registry = provider_registry or NodeProviderRegistry()

    def build(self, contract: NodeProviderContract, context: RuntimeBuildContext) -> RuntimeContribution:
        package_root = context.package_root if context is not None else Path.cwd()
        return RuntimeContribution(
            node_providers=self.provider_registry.resolve_references(
                [item.model_dump(mode="json") for item in contract.config.providers],
                package_root=package_root,
            )
        )


class ArtifactContractBuilder:
    contract_type = "artifact"
    contract_version = "artifact_contract.v0"

    def build(self, contract: ArtifactContract, context: RuntimeBuildContext) -> RuntimeContribution:
        config = contract.config.model_copy(
            update={
                "root": package_runtime_path_text(context, contract.config.root, field_path="artifact.config.root"),
            }
        )
        artifact_store = ArtifactStore(
            root=config.root,
            allowed_kinds=config.allowed_kinds,
        )
        return RuntimeContribution(
            services={
                "artifact_store": artifact_store,
                "report_store": ReportStore(artifact_store=artifact_store),
            },
            tool_runtime_resources={"artifact_store": artifact_store},
        )


class ResourcesContractBuilder:
    contract_type = "resources"
    contract_version = "resources_contract.v0"

    def build(self, contract: ResourcesContract, context: RuntimeBuildContext) -> RuntimeContribution:
        from agent_factory.resource_system import PackageResourceResolver, RESOURCE_RESOLVER_KEY, ResourceStore

        descriptors = {item.resource_id: item for item in contract.config.resource_descriptors}
        resolver = PackageResourceResolver(
            package_id=context.package.package_root.name,
            descriptors=descriptors,
            store=ResourceStore(),
        )
        return RuntimeContribution(tool_runtime_resources={RESOURCE_RESOLVER_KEY: resolver})


class SchedulerContractBuilder:
    contract_type = "scheduler"
    contract_version = "scheduler_contract.v0"

    def build(self, contract: SchedulerContract, context: RuntimeBuildContext) -> RuntimeContribution:
        config = contract.config.model_copy(
            update={
                "store_path": package_runtime_path_text(
                    context,
                    contract.config.store_path,
                    field_path="scheduler.config.store_path",
                )
            }
        )
        owner_id = context.package.assembly_spec.agent.id
        store = SQLiteSchedulerStore(config.store_path)
        runtime = SchedulerRuntime(
            config=config,
            owner_type="agent",
            owner_id=owner_id,
            store=store,
            executor=SchedulerExecutor(),
        )
        worker = SchedulerWorker(runtime)
        return RuntimeContribution(
            services={"scheduler_store": store, "scheduler_runtime": runtime},
            tool_runtime_resources={
                "scheduler_runtime": runtime,
                "runtime_execution_config": {
                    "user_config": {},
                    "runtime_request": {},
                },
            },
            background_workers=[worker],
        )


class SchedulerSeedContractBuilder:
    contract_type = "scheduler_seed"
    contract_version = "scheduler_seed_contract.v0"

    def build(self, contract: SchedulerSeedContract, context: RuntimeBuildContext) -> RuntimeContribution:
        del contract, context
        return RuntimeContribution()


class DependenciesContractBuilder:
    contract_type = "dependencies"
    contract_version = "dependencies_contract.v1"

    def build(self, contract: DependenciesContract, context: RuntimeBuildContext) -> RuntimeContribution:
        del contract, context
        return RuntimeContribution()


def _runtime_tool_executor(tool_id: str, tool) -> Any:
    def execute(arguments: dict[str, Any], _state: Any) -> ToolExecutionResult:
        try:
            output = tool.invoke(arguments)
        except GraphInterrupt:
            raise
        except Exception as exc:
            return ToolExecutionResult(
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                observation_summary=f"{tool_id} failed: {type(exc).__name__}",
            )
        if isinstance(output, dict):
            if output.get("type") == "tool_observation":
                return _tool_observation_result(output)
            status = str(output.get("status") or "completed")
            if status not in {"completed", "failed", "interrupted"}:
                status = "completed"
            return ToolExecutionResult(
                status=status,  # type: ignore[arg-type]
                output=output,
                error=output.get("error"),
                interrupt_type=output.get("interrupt_type"),
                observation_summary=output.get("observation_summary"),
            )
        return ToolExecutionResult(status="completed", output={"value": output})

    return execute


def _tool_observation_result(observation: dict[str, Any]) -> ToolExecutionResult:
    observation_status = str(observation.get("status") or "")
    message = str(observation.get("message") or observation_status or "tool observation")
    if observation_status == "completed":
        return ToolExecutionResult(
            status="completed",
            output=observation,
            observation_summary=message,
            metadata={"tool_observation_status": observation_status},
        )
    return ToolExecutionResult(
        status="failed",
        output=observation,
        error=message,
        observation_summary=message,
        metadata={"tool_observation_status": observation_status},
    )


def _merge_tool_resources(
    *,
    serializable_resources: dict[str, object],
    provider_runtime_resources: dict[str, Any],
    tool_runtime_resources: dict[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(serializable_resources)
    for source_name, source in (
        ("provider runtime resource", provider_runtime_resources),
        ("tool runtime resource", tool_runtime_resources),
    ):
        for key, value in source.items():
            if key in merged and merged[key] is not value and merged[key] != value:
                raise ValueError(f"conflicting {source_name}: {key}")
            merged[key] = value
    return merged


def _tool_output_root(*, context: RuntimeBuildContext, instance_extension_root: Path) -> Path:
    if context.runtime_root is not None:
        return context.runtime_root / "tool_outputs"
    if instance_extension_root.name == "extensions":
        return instance_extension_root.parent / "tool_outputs"
    return instance_extension_root / "tool_outputs"


def _instance_tool_approval_policy(instance_extension_root: Path) -> ToolApprovalPolicyConfig | None:
    return load_tool_approval_policy_file(instance_extension_root / "tool_permissions.json")


def _inherits_builtin_agent_extensions(package: Any) -> bool:
    runtime = getattr(getattr(package, "manifest", None), "runtime", {}) or {}
    return bool(runtime.get("system_package")) if isinstance(runtime, dict) else False


def _package_extension_roots(context: RuntimeBuildContext) -> list[Path]:
    return [context.package_root / "extensions"]
