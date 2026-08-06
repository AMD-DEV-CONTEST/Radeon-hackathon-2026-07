from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.tooling.builtins.aliases import canonical_builtin_tool_ids

ServiceKind = Literal[
    "model_service",
    "model_operation_service",
    "tool_registry",
    "memory_store",
    "memory_system",
    "knowledge_runtime",
    "context_engine",
    "observability_manager",
    "trace_recorder",
    "trace_reader",
    "trace_projector",
    "trace_diagnostics",
    "checkpointer",
    "harness_bridge",
]

HookPoint = Literal[
    "pre_cognitive",
    "post_cognitive",
    "pre_operational",
    "post_operational",
    "pre_terminal",
    "post_terminal",
    "on_interrupt",
    "on_resume",
]

BindingType = Literal[
    "prompt",
    "tool_access",
    "model_operation",
    "strategy_profile",
    "output_formatter",
    "custom",
]


class ServiceBindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str
    kind: ServiceKind
    required: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class NodeBindingTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    impl: str


class PromptBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    template: str
    variables: list[str] = Field(default_factory=list)


class ToolAccessBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_tool_ids: list[str] = Field(default_factory=list)
    approval_policy: str = "allow_below_high"

    @field_validator("allowed_tool_ids")
    @classmethod
    def _canonicalize_builtin_tool_ids(cls, value: list[str]) -> list[str]:
        return canonical_builtin_tool_ids(value)


class ModelOperationWriteTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: Literal["package_state", "context"]
    namespace: str | None = None
    path: list[str] = Field(default_factory=list)

    @field_validator("namespace")
    @classmethod
    def _namespace_is_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        namespace = value.strip()
        if not namespace:
            raise ValueError("write_target.namespace must not be empty")
        if not namespace.replace("_", "").replace(".", "").isalnum() or namespace[0].isdigit():
            raise ValueError("write_target.namespace must use lowercase alphanumeric, underscore, and dot segments")
        for part in namespace.split("."):
            if not part or not part[0].isalpha() or part.lower() != part:
                raise ValueError("write_target.namespace segments must start with a lowercase letter")
        return namespace

    @field_validator("path")
    @classmethod
    def _path_segments_are_valid(cls, value: list[str]) -> list[str]:
        segments: list[str] = []
        for item in value:
            segment = str(item).strip()
            if not segment or segment in {".", ".."}:
                raise ValueError("write_target.path must contain only non-empty field segments")
            if "/" in segment:
                raise ValueError("write_target.path segments must not contain '/'")
            segments.append(segment)
        return segments

    @model_validator(mode="after")
    def _target_is_complete(self) -> "ModelOperationWriteTarget":
        if self.section == "package_state" and not self.namespace:
            raise ValueError("package_state write_target requires namespace")
        if self.section == "context" and (self.namespace or self.path):
            raise ValueError("context write_target writes to context.model_outputs[node_id] and must not set namespace/path")
        return self


class ModelOperationBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["chat", "tool_bound_chat", "structured_json"]
    model_role: Literal["main", "task", "compression"] = "main"
    output_schema: dict[str, Any] = Field(default_factory=dict)
    write_target: ModelOperationWriteTarget
    max_attempts: int = Field(default=5, ge=1)
    structured_method: str | None = None
    prompt_id: str | None = None

    @field_validator("output_schema")
    @classmethod
    def _output_schema_is_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("model_operation.output_schema must be a non-empty JSON schema object")
        return value

    @field_validator("prompt_id")
    @classmethod
    def _prompt_id_is_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        prompt_id = value.strip()
        if not prompt_id:
            raise ValueError("model_operation.prompt_id must not be empty")
        return prompt_id

    @field_validator("structured_method")
    @classmethod
    def _structured_method_is_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        method = value.strip()
        if not method:
            raise ValueError("model_operation.structured_method must not be empty")
        return method

class StrategyProfileBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class OutputFormatterBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formatter_id: str
    mode: str = "identity"
    config: dict[str, Any] = Field(default_factory=dict)


class CustomBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extension_id: str
    schema_version: str = "v0"
    purpose: str
    config: dict[str, Any] = Field(default_factory=dict)


StandardNodeBindingPayload = (
    PromptBindingPayload
    | ToolAccessBindingPayload
    | ModelOperationBindingPayload
    | StrategyProfileBindingPayload
    | OutputFormatterBindingPayload
    | CustomBindingPayload
)


class NodeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    binding_type: BindingType
    target: NodeBindingTarget
    payload: StandardNodeBindingPayload

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload_for_binding_type(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        binding_type = data.get("binding_type")
        payload = data.get("payload")
        payload_model = _payload_model_for_binding_type(binding_type)
        if payload_model is not None and isinstance(payload, dict):
            data = dict(data)
            data["payload"] = payload_model.model_validate(payload)
        return data

    @model_validator(mode="after")
    def _payload_matches_binding_type(self) -> "NodeBinding":
        payload_model = _payload_model_for_binding_type(self.binding_type)
        if payload_model is None:
            return self
        if not isinstance(self.payload, payload_model):
            raise ValueError(f"payload must match binding_type={self.binding_type}")
        return self


class HookBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    hook_point: HookPoint
    enabled: bool = True
    order: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class BindingSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[ServiceBindingSpec] = Field(default_factory=list)
    node_bindings: list[NodeBinding] = Field(default_factory=list)
    hooks: list[HookBinding] = Field(default_factory=list)


def _payload_model_for_binding_type(binding_type: Any) -> type[BaseModel] | None:
    return {
        "prompt": PromptBindingPayload,
        "tool_access": ToolAccessBindingPayload,
        "model_operation": ModelOperationBindingPayload,
        "strategy_profile": StrategyProfileBindingPayload,
        "output_formatter": OutputFormatterBindingPayload,
        "custom": CustomBindingPayload,
    }.get(str(binding_type))
