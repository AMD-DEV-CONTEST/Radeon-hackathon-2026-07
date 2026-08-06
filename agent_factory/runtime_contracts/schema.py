from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from agent_factory.context_system import ContextContractConfig
from agent_factory.model_pool.schema import ModelBindingRole, ModelProfileBinding, ModelToolBinding
from agent_factory.paths import cross_platform_absolute_path
from agent_factory.scheduler_system.schema import SchedulerContractConfig, SchedulerSeedContractConfig
from agent_factory.trace_system.schema import TraceContractConfig
from agent_factory.tooling.approval_policy import ToolApprovalPolicyConfig
from agent_factory.tooling.builtins.aliases import canonical_builtin_tool_ids
from agent_factory.runtime_defaults import (
    DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS,
    DEFAULT_BUILTIN_WORKSPACE_ROOT,
)


PACKAGE_INFRASTRUCTURE_CONTRACTS = frozenset({"artifact", "render", "sandbox", "trace"})
RETIRED_AGENT_PACKAGE_CONTRACTS = frozenset({"knowledge", "memory", "session", "state"})
REQUIRED_AGENT_PACKAGE_CONTRACTS = frozenset(
    {
        "context",
        "dependencies",
        "model",
        "resources",
        "scheduler",
        "tools",
    }
)
OPTIONAL_AGENT_PACKAGE_CONTRACTS = frozenset({"scheduler_seed"})
SUPPORTED_AGENT_PACKAGE_CONTRACTS = (
    REQUIRED_AGENT_PACKAGE_CONTRACTS | OPTIONAL_AGENT_PACKAGE_CONTRACTS
)


class AgentIdentitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None = None
    description: str | None = None
    version: str = "0.1.0"


AgentPackageAgentSpec = AgentIdentitySpec


class AgentPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["agent_package.v0"] = "agent_package.v0"
    factory_run_id: str
    agent: AgentPackageAgentSpec
    runtime: dict[str, Any] = Field(default_factory=dict)
    assembly_spec_path: str
    contracts: dict[str, str] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_referenced_paths(self) -> "AgentPackageManifest":
        missing_contracts = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - set(self.contracts))
        if missing_contracts:
            raise ValueError("agent package missing required contracts: " + ", ".join(missing_contracts))
        infrastructure_contracts = sorted(PACKAGE_INFRASTRUCTURE_CONTRACTS & set(self.contracts))
        if infrastructure_contracts:
            raise ValueError(
                "agent package must not declare runtime infrastructure contracts: "
                + ", ".join(infrastructure_contracts)
            )
        retired_contracts = sorted(RETIRED_AGENT_PACKAGE_CONTRACTS & set(self.contracts))
        if retired_contracts:
            raise ValueError(
                "agent package declares retired contracts: "
                + ", ".join(retired_contracts)
            )
        unsupported_contracts = sorted(set(self.contracts) - SUPPORTED_AGENT_PACKAGE_CONTRACTS)
        if unsupported_contracts:
            raise ValueError(
                "agent package declares unsupported contracts: "
                + ", ".join(unsupported_contracts)
            )
        for key in (
            "assembly_spec_path",
        ):
            _validate_package_relative_path(str(getattr(self, key)), field_name=key)
        for key, value in self.contracts.items():
            if not key.strip():
                raise ValueError("contracts keys must be non-empty")
            _validate_package_relative_path(value, field_name=f"contracts.{key}")
        for value in self.tools:
            _validate_package_relative_path(value, field_name="tools")
        return self


class RuntimeContractEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    version: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class ToolsContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    builtin_tools_enabled: bool = True
    builtin_tool_ids: list[str] = Field(default_factory=list)
    builtin_workspace_root: str = DEFAULT_BUILTIN_WORKSPACE_ROOT
    builtin_allow_external_paths: bool = DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS
    package_tools_enabled: bool = True
    instance_extensions_enabled: bool = True
    instance_extension_root: str = ".agent_runtime/extensions"
    approval_policy: ToolApprovalPolicyConfig | None = None

    @field_validator("builtin_tool_ids")
    @classmethod
    def _builtin_tool_ids_are_not_empty(cls, value: list[str]) -> list[str]:
        ids: list[str] = []
        for item in value:
            tool_id = str(item).strip()
            if not tool_id:
                raise ValueError("builtin_tool_ids must not contain empty ids")
            ids.append(tool_id)
        return canonical_builtin_tool_ids(ids)

    @field_validator("builtin_workspace_root")
    @classmethod
    def _builtin_workspace_root_is_absolute(cls, value: str) -> str:
        root = str(value).strip()
        if not root:
            raise ValueError("builtin_workspace_root must not be empty")
        path = cross_platform_absolute_path(root)
        if path is None:
            raise ValueError("builtin_workspace_root must be an absolute workspace path")
        if path == type(path)(path.anchor):
            raise ValueError("builtin_workspace_root must not be a filesystem root")
        return root

    @field_validator("instance_extension_root")
    @classmethod
    def _extension_root_is_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("instance_extension_root must not be empty")
        return value


class ToolsContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tools"] = "tools"
    version: Literal["tools_contract.v0"] = "tools_contract.v0"
    enabled: bool = True
    config: ToolsContractConfig = Field(default_factory=ToolsContractConfig)


class ContextContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["context"] = "context"
    version: Literal["context_contract.v1"] = "context_contract.v1"
    enabled: bool = True
    config: ContextContractConfig = Field(default_factory=ContextContractConfig)


class TraceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["trace"] = "trace"
    version: Literal["trace_contract.v0"] = "trace_contract.v0"
    enabled: bool = True
    config: TraceContractConfig = Field(default_factory=TraceContractConfig)


class ModelContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bindings: dict[ModelBindingRole, ModelProfileBinding] = Field(default_factory=dict)
    tool_bindings: dict[str, ModelToolBinding] = Field(default_factory=dict)

    @field_validator("bindings")
    @classmethod
    def _bindings_are_not_empty_ids(
        cls,
        value: dict[ModelBindingRole, ModelProfileBinding],
    ) -> dict[ModelBindingRole, ModelProfileBinding]:
        return dict(value)

    @field_validator("tool_bindings")
    @classmethod
    def _tool_binding_ids_are_tool_ids(
        cls,
        value: dict[str, ModelToolBinding],
    ) -> dict[str, ModelToolBinding]:
        result: dict[str, ModelToolBinding] = {}
        for tool_id, binding in value.items():
            clean_id = str(tool_id or "").strip()
            if not clean_id or not clean_id.replace("_", "").isalnum() or clean_id[0].isdigit() or clean_id.lower() != clean_id:
                raise ValueError("model tool binding ids must be lowercase snake_case")
            result[clean_id] = binding
        return result


class ModelContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["model"] = "model"
    version: Literal["model_contract.v1"] = "model_contract.v1"
    enabled: bool = True
    config: ModelContractConfig = Field(default_factory=ModelContractConfig)


class NodeProviderReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_id")
    @classmethod
    def _provider_id_is_not_empty(cls, value: str) -> str:
        provider_id = str(value).strip()
        if not provider_id:
            raise ValueError("node provider provider_id must not be empty")
        return provider_id


class NodeProviderContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[NodeProviderReference] = Field(default_factory=list)

    @field_validator("providers")
    @classmethod
    def _providers_are_unique(cls, value: list[NodeProviderReference]) -> list[NodeProviderReference]:
        seen: set[str] = set()
        for item in value:
            if item.provider_id in seen:
                raise ValueError(f"duplicate node provider reference: {item.provider_id}")
            seen.add(item.provider_id)
        return value


class NodeProviderContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["node_provider"] = "node_provider"
    version: Literal["node_provider_contract.v0"] = "node_provider_contract.v0"
    enabled: bool = True
    config: NodeProviderContractConfig = Field(default_factory=NodeProviderContractConfig)


class ArtifactContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = ".agent_runtime/artifacts"
    allowed_kinds: list[str] = Field(default_factory=lambda: ["report", "artifact"])

    @field_validator("root")
    @classmethod
    def _artifact_path_is_safe(cls, value: str) -> str:
        raw = str(value).strip()
        if not raw:
            raise ValueError("artifact paths must not be empty")
        path = PurePosixPath(raw)
        if path == PurePosixPath("/"):
            raise ValueError("artifact paths must not point at the container root")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("artifact paths must not contain empty, current, or parent segments")
        return raw

    @field_validator("allowed_kinds")
    @classmethod
    def _allowed_kinds_are_valid(cls, value: list[str]) -> list[str]:
        kinds: list[str] = []
        seen: set[str] = set()
        for item in value:
            kind = str(item).strip()
            if not kind:
                raise ValueError("allowed_kinds must not contain empty values")
            if "/" in kind or ".." in kind:
                raise ValueError("artifact kind must be a simple identifier")
            if kind not in seen:
                kinds.append(kind)
                seen.add(kind)
        if not kinds:
            raise ValueError("allowed_kinds must not be empty")
        return kinds


class ArtifactContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["artifact"] = "artifact"
    version: Literal["artifact_contract.v0"] = "artifact_contract.v0"
    enabled: bool = True
    config: ArtifactContractConfig = Field(default_factory=ArtifactContractConfig)


class ResourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    description: str = ""
    required: bool = True
    value_schema: dict[str, Any] = Field(default_factory=dict)
    default_value: Any = Field(default_factory=dict)
    secret_fields: list[str] = Field(default_factory=list)
    used_by: list[str] = Field(default_factory=list)
    sandbox_access_expectation: str = ""

    @field_validator("resource_id")
    @classmethod
    def _resource_id_is_clean(cls, value: str) -> str:
        resource_id = value.strip()
        if not resource_id:
            raise ValueError("resource_id must not be empty")
        return resource_id


class ResourcesContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_descriptors: list[ResourceDescriptor] = Field(default_factory=list)


class ResourcesContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["resources"] = "resources"
    version: Literal["resources_contract.v0"] = "resources_contract.v0"
    enabled: bool = True
    config: ResourcesContractConfig = Field(default_factory=ResourcesContractConfig)


class DependenciesContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python_requirements: list[str] = Field(default_factory=list)
    system_packages: SkipJsonSchema[list[str]] = Field(default_factory=list, exclude=True)
    npm_requirements: list[str] = Field(default_factory=list)
    system_binaries: list[str] = Field(default_factory=list)
    platform_architectures: list[Literal["amd64", "arm64"]] = Field(default_factory=list)
    base_image: SkipJsonSchema[str] = Field(default="local-python", exclude=True)
    verification_commands: list[list[str]] = Field(default_factory=list)
    install_timeout_seconds: int | None = Field(default=None, ge=1)


class DependenciesContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["dependencies"] = "dependencies"
    version: Literal["dependencies_contract.v1"] = "dependencies_contract.v1"
    enabled: bool = True
    config: DependenciesContractConfig = Field(default_factory=DependenciesContractConfig)


class SchedulerContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["scheduler"] = "scheduler"
    version: Literal["scheduler_contract.v0"] = "scheduler_contract.v0"
    enabled: bool = True
    config: SchedulerContractConfig = Field(default_factory=SchedulerContractConfig)


class SchedulerSeedContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["scheduler_seed"] = "scheduler_seed"
    version: Literal["scheduler_seed_contract.v0"] = "scheduler_seed_contract.v0"
    enabled: bool = True
    config: SchedulerSeedContractConfig = Field(default_factory=SchedulerSeedContractConfig)


def _validate_package_relative_path(value: str, *, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError(f"{field_name} must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} must not contain empty, current, or parent segments")
    return value
