from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from agent_factory.tooling.entrypoint import ToolEntrypointLoader
from agent_factory.tooling.entrypoints import EntrypointAdapterRegistry, MCPToolClient
from agent_factory.tooling.execution_context import current_tool_call
from agent_factory.tooling.approval_policy import ToolApprovalPolicyConfig, default_tool_approval_policy
from agent_factory.tooling.envelope import is_tool_envelope, tool_envelope
from agent_factory.tooling.gateway import (
    ToolApprovalHandler,
    ToolExecutionGateway,
    default_tool_max_revisions,
)
from agent_factory.resource_system import RESOURCE_RESOLVER_KEY
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore, default_tool_output_policy
from agent_factory.tooling.package_tool_spec import is_package_tool_entrypoint
from agent_factory.tooling.risk import ToolRiskEvaluator
from agent_factory.tooling.schema_compiler import compile_json_schema
from agent_factory.tooling.spec import ToolSpec


class ToolCompileError(ValueError):
    pass


class ToolCompiler:
    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        resources: Mapping[str, Any] | None = None,
        approval_handler: ToolApprovalHandler | None = None,
        approval_policy: ToolApprovalPolicyConfig | None = None,
        max_revisions: int | None = None,
        entrypoint_loader: ToolEntrypointLoader | None = None,
        allowed_python_roots: list[str | Path] | None = None,
        adapter_registry: EntrypointAdapterRegistry | None = None,
        mcp_clients: Mapping[str, MCPToolClient] | None = None,
    ) -> None:
        self.package_root = Path(package_root).resolve() if package_root else None
        self.loader = entrypoint_loader or ToolEntrypointLoader(
            package_root=package_root,
            allowed_python_roots=allowed_python_roots,
            adapter_registry=adapter_registry,
            mcp_clients=mcp_clients,
        )
        self.resources = resources or {}
        self.approval_handler = approval_handler
        self.approval_policy = approval_policy or default_tool_approval_policy()
        self.max_revisions = max_revisions or default_tool_max_revisions()
        self.output_store = _output_store_from_resources(self.resources)
        self.output_policy = default_tool_output_policy()

    def compile(self, spec: ToolSpec) -> BaseTool:
        try:
            input_schema = compile_json_schema(schema=spec.input_schema, model_name=f"{spec.id}_args")
            output_schema = compile_json_schema(schema=spec.output_schema, model_name=f"{spec.id}_output")
            entrypoint = (
                _lazy_package_entrypoint(spec, self.loader)
                if _is_package_tool_spec(spec)
                else self.loader.load(spec.entrypoint)
            )
            entrypoint = _entrypoint_for_spec(spec, entrypoint)
            hard_risk_evaluator = self._load_hard_risk_evaluator(spec)
            llm_risk_prompt = self._load_llm_risk_prompt(spec)
        except Exception as exc:
            raise ToolCompileError(f"cannot compile tool {spec.id}: {exc}") from exc
        gateway = ToolExecutionGateway(
            spec=spec,
            input_schema=input_schema,
            output_schema=output_schema,
            entrypoint=entrypoint,
            global_resources=self.resources,
            resource_resolver=self.resources.get(RESOURCE_RESOLVER_KEY),
            hard_risk_evaluator=hard_risk_evaluator,
            llm_risk_prompt=llm_risk_prompt,
            approval_handler=self.approval_handler,
            approval_policy=self.approval_policy,
            max_revisions=self.max_revisions,
            output_store=self.output_store,
            output_policy=self.output_policy,
        )

        def invoke_tool(**kwargs: Any) -> dict[str, Any]:
            current = current_tool_call()
            arguments = _strip_unset_none_values(
                _normalize_tool_arguments(dict(kwargs)),
                schema=spec.input_schema,
            )
            return gateway.execute(
                arguments,
                tool_call_id=current.tool_call_id if current is not None and current.tool_id == spec.id else None,
            )

        return StructuredTool.from_function(
            func=invoke_tool,
            name=spec.id,
            description=spec.description,
            args_schema=input_schema.schema,
            infer_schema=False,
            metadata={
                "agent_factory": {
                    "tool_id": spec.id,
                    "concurrent": spec.concurrent,
                    "risk_level": spec.risk_level,
                    "approval_request": gateway.approval_request,
                    "loop_policy": spec.loop_policy.model_dump(mode="json", exclude_none=True),
                    "sensitive_argument_paths": list(spec.sensitive_argument_paths),
                    "base_description": spec.description,
                    "description_context": spec.description_context.model_dump(mode="json"),
                }
            },
            handle_validation_error=lambda error: json.dumps(
                {
                    "type": "tool_observation",
                    "status": "invalid_arguments",
                    "tool_id": spec.id,
                    "message": "Tool arguments failed transport validation.",
                    "retryable": True,
                    "errors": [str(error)],
                },
                ensure_ascii=False,
            ),
        )

    def compile_many(self, specs: Iterable[ToolSpec]) -> list[BaseTool]:
        return [self.compile(spec) for spec in specs]

    def _load_hard_risk_evaluator(self, spec: ToolSpec) -> ToolRiskEvaluator | None:
        if not spec.risk_evaluator.hard:
            return None
        value = spec.risk_evaluator.hard
        try:
            return self.loader.load_risk_evaluator(value)
        except Exception as exc:
            raise ValueError(f"risk_evaluator.hard invalid entrypoint {value!r}: {exc}") from exc

    def _load_llm_risk_prompt(self, spec: ToolSpec) -> str | None:
        value = spec.risk_evaluator.llm
        if not value:
            return None
        if self.package_root is None:
            return value
        candidate = (self.package_root / value).resolve()
        try:
            candidate.relative_to(self.package_root)
        except ValueError as exc:
            raise ToolCompileError(f"llm risk prompt escapes package root: {value}") from exc
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
        if value.endswith(".md"):
            raise ToolCompileError(f"llm risk prompt file does not exist: {value}")
        return value


def _normalize_tool_arguments(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize_tool_arguments(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: _normalize_tool_arguments(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_tool_arguments(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_tool_arguments(item) for item in value]
    return value


def _strip_unset_none_values(value: Any, *, schema: dict[str, Any]) -> Any:
    if not isinstance(value, dict) or not isinstance(schema, dict):
        return value
    if _schema_type(schema) != "object":
        return value
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return value
    required = set(schema.get("required") or [])
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        field_schema = properties.get(key)
        if not isinstance(field_schema, dict):
            cleaned[key] = item
            continue
        if item is None and key not in required and not _schema_accepts_null(field_schema):
            continue
        cleaned[key] = _strip_nested_none_values(item, schema=field_schema)
    return cleaned


def _strip_nested_none_values(value: Any, *, schema: dict[str, Any]) -> Any:
    schema_type = _schema_type(schema)
    if schema_type == "object" and isinstance(value, dict):
        return _strip_unset_none_values(value, schema=schema)
    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return value
        return [_strip_nested_none_values(item, schema=item_schema) for item in value]
    return value


def _schema_type(schema: dict[str, Any]) -> Any:
    return schema.get("type", "object")


def _schema_accepts_null(schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "null":
        return True
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    for keyword in ("anyOf", "oneOf"):
        options = schema.get(keyword)
        if isinstance(options, list) and any(
            isinstance(option, dict) and _schema_accepts_null(option) for option in options
        ):
            return True
    return False


def _output_store_from_resources(resources: Mapping[str, Any]) -> ToolOutputStore | None:
    value = resources.get(TOOL_OUTPUT_STORE_RESOURCE)
    return value if isinstance(value, ToolOutputStore) else None


def _entrypoint_for_spec(spec: ToolSpec, entrypoint):
    if not _is_package_tool_spec(spec):
        return entrypoint

    def invoke(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
        output = entrypoint(arguments=arguments, resources=resources)
        if is_tool_envelope(output):
            return output
        if isinstance(output, dict):
            return tool_envelope(
                output,
                evidence={"package_tool_output": {"wrapped_raw_output": True}},
                summary=f"Package tool {spec.id} completed.",
            )
        return output

    return invoke


def _is_package_tool_spec(spec: ToolSpec) -> bool:
    return spec.permission_scope == "package" and is_package_tool_entrypoint(spec.id, spec.entrypoint)


def _lazy_package_entrypoint(spec: ToolSpec, loader: ToolEntrypointLoader):
    cached_entrypoint = None
    load_lock = RLock()

    def invoke(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
        nonlocal cached_entrypoint
        if cached_entrypoint is None:
            with load_lock:
                if cached_entrypoint is None:
                    cached_entrypoint = loader.load(spec.entrypoint)
        return cached_entrypoint(arguments=arguments, resources=resources)

    return invoke
