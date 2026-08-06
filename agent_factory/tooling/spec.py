from __future__ import annotations

import re
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SNAKE_CASE_ID = re.compile(r"^[a-z][a-z0-9_]*$")

ToolObservationStatus = Literal[
    "cancelled",
    "denied",
    "revision_requested",
    "resource_required",
    "invalid_arguments",
    "invalid_output",
    "execution_failed",
    "completed",
]
ToolExecutionStatus = Literal["completed", "failed"]
ToolContractStatus = Literal["valid", "invalid"]

ToolRiskLevel = Literal["low", "medium", "high"]
ToolRiskAction = Literal["inherit", "allow", "ask", "deny", "uncertain"]
ToolLLMRiskMode = Literal["disabled", "on_uncertain", "always"]
ToolPermissionScope = Literal["system", "package", "extension", "model"]
ToolOutputCompressionMode = Literal["structured_json", "deterministic"]
ToolOutputProjectionMode = Literal["compress", "passthrough"]

ToolEventType = Literal[
    "tool_call_proposed",
    "tool_approval_requested",
    "tool_approval_resolved",
    "tool_call_started",
    "tool_call_completed",
    "tool_contract_invalid",
    "tool_call_failed",
    "tool_observation_available",
]


class ToolRiskEvaluatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard: str | None = None
    llm: str | None = None
    llm_mode: ToolLLMRiskMode = "disabled"


class ToolDescriptionContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_date: bool = False
    timezone: str = "Asia/Shanghai"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        timezone_name = str(value or "").strip()
        if not timezone_name:
            raise ValueError("tool description context timezone must be non-empty")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown tool description context timezone: {timezone_name}") from exc
        return timezone_name


class ToolRiskContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    base_risk_level: ToolRiskLevel
    arguments: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    tool_call: dict[str, Any] = Field(default_factory=dict)


class ToolRiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ToolRiskAction = "inherit"
    risk_level: ToolRiskLevel | None = None
    reasons: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    normalized_arguments: dict[str, Any] | None = None


class ToolOutputCompressionActionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ToolOutputCompressionMode = "structured_json"
    prompt: str = ""
    schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema")
    @classmethod
    def validate_schema_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("compression schema must be a JSON object")
        return value


class ToolOutputCompressionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_model_chars: int | None = Field(default=None, ge=1000, le=1_000_000)
    action_argument: str = "action"
    actions: dict[str, ToolOutputCompressionActionConfig] = Field(default_factory=dict)

    @field_validator("action_argument")
    @classmethod
    def validate_action_argument(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("action_argument must be non-empty")
        return text


class ToolLoopPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_calls: int | None = Field(default=None, ge=1)
    max_identical_calls: int | None = Field(default=None, ge=1)
    max_semantic_calls: int | None = Field(default=None, ge=1)
    max_consecutive_failures: int | None = Field(default=None, ge=1)
    max_consecutive_empty_results: int | None = Field(default=None, ge=1)
    max_consecutive_no_new_evidence: int | None = Field(default=None, ge=1)
    semantic_argument_pointers: list[str] = Field(default_factory=list)
    evidence_output_pointers: list[str] = Field(default_factory=list)

    @field_validator("semantic_argument_pointers", "evidence_output_pointers")
    @classmethod
    def validate_json_pointers(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            pointer = str(item or "").strip()
            if not pointer.startswith("/"):
                raise ValueError("tool loop policy pointers must be JSON Pointers beginning with '/'")
            if pointer not in result:
                result.append(pointer)
        return result

    @model_validator(mode="after")
    def validate_required_pointers(self) -> "ToolLoopPolicyConfig":
        bounded_fields = (
            self.max_identical_calls,
            self.max_semantic_calls,
            self.max_consecutive_failures,
            self.max_consecutive_empty_results,
            self.max_consecutive_no_new_evidence,
        )
        if any(value is not None for value in bounded_fields) and self.max_calls is None:
            raise ValueError("tool loop policies require max_calls as a total state bound")
        if self.max_semantic_calls is not None and not self.semantic_argument_pointers:
            raise ValueError("max_semantic_calls requires semantic_argument_pointers")
        if (
            self.max_consecutive_empty_results is not None
            or self.max_consecutive_no_new_evidence is not None
        ) and not self.evidence_output_pointers:
            raise ValueError("empty/no-new-evidence budgets require evidence_output_pointers")
        return self

    @property
    def enabled(self) -> bool:
        return any(
            value is not None
            for value in (
                self.max_calls,
                self.max_identical_calls,
                self.max_semantic_calls,
                self.max_consecutive_failures,
                self.max_consecutive_empty_results,
                self.max_consecutive_no_new_evidence,
            )
        )


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    description_context: ToolDescriptionContextConfig = Field(default_factory=ToolDescriptionContextConfig)
    schema_error_guidance: str = ""
    entrypoint: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, str] = Field(default_factory=dict)
    risk_level: ToolRiskLevel = "low"
    risk_evaluator: ToolRiskEvaluatorConfig = Field(default_factory=ToolRiskEvaluatorConfig)
    concurrent: bool = True
    permission_scope: ToolPermissionScope = "package"
    permission_tags: list[str] = Field(default_factory=list)
    output_compression: ToolOutputCompressionConfig = Field(default_factory=ToolOutputCompressionConfig)
    output_projection: ToolOutputProjectionMode = "compress"
    loop_policy: ToolLoopPolicyConfig = Field(default_factory=ToolLoopPolicyConfig)
    sensitive_argument_paths: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not SNAKE_CASE_ID.fullmatch(value):
            raise ValueError("tool id must be snake_case")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("entrypoint must use '<path_or_module>:<function>'")
        if value.startswith("mcp:"):
            target = value.removeprefix("mcp:")
            if "/" not in target:
                raise ValueError("MCP entrypoint must use 'mcp:<server_id>/<tool_name>'")
            server_id, tool_name = target.split("/", 1)
            if not server_id.strip() or not tool_name.strip():
                raise ValueError("MCP server_id and tool_name must be non-empty")
            return value
        target, function = value.rsplit(":", 1)
        if not target.strip() or not function.strip():
            raise ValueError("entrypoint target and function must be non-empty")
        return value

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("schema must be a JSON object")
        return value

    @field_validator("resources")
    @classmethod
    def validate_resources(cls, value: dict[str, str]) -> dict[str, str]:
        for local_name, global_key in value.items():
            if not local_name or not global_key:
                raise ValueError("resource local names and global keys must be non-empty")
        return value

    @field_validator("permission_tags")
    @classmethod
    def validate_permission_tags(cls, value: list[str]) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()
        for item in value:
            tag = str(item).strip().lower().replace("-", "_")
            if not tag:
                continue
            if not SNAKE_CASE_ID.fullmatch(tag):
                raise ValueError("permission tags must be snake_case")
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
        return tags

    @field_validator("sensitive_argument_paths")
    @classmethod
    def validate_sensitive_argument_paths(cls, value: list[str]) -> list[str]:
        paths: list[str] = []
        for item in value:
            path = str(item).strip()
            if not path.startswith("/"):
                raise ValueError("sensitive argument paths must be JSON Pointers beginning with '/'")
            if path not in paths:
                paths.append(path)
        return paths


class ModelToolView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: ToolRiskLevel = "low"
    permission_scope: ToolPermissionScope = "package"
    permission_tags: list[str] = Field(default_factory=list)


class ToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_observation"] = "tool_observation"
    status: ToolObservationStatus
    tool_id: str
    tool_call_id: str | None = None
    message: str
    user_instruction: str | None = None
    retryable: bool = True
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    output_ref: dict[str, Any] | None = None
    output_summary: str | None = None
    output_truncated: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)
    execution_status: ToolExecutionStatus = "failed"
    contract_status: ToolContractStatus = "valid"
    errors: list[str] = Field(default_factory=list)


class ToolEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str | None = None
    tool_id: str
    node_id: str | None = None
    stage_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str
    output: dict[str, Any] | None = None
    output_ref: dict[str, Any] | None = None
    output_summary: str | None = None
    output_truncated: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)
    execution_status: str = ""
    contract_status: str = ""
    observation: dict[str, Any] | None = None
    message: str = ""


def model_tool_view(spec: ToolSpec) -> ModelToolView:
    return ModelToolView(
        id=spec.id,
        description=spec.description,
        input_schema=spec.input_schema,
        risk_level=spec.risk_level,
        permission_scope=spec.permission_scope,
        permission_tags=spec.permission_tags,
    )
