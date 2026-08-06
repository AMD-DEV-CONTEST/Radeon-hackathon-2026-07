from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from agent_factory.runtime_kernel.adapters.model import ModelRole
from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.tooling.schema_compiler import compile_json_schema


class CognitiveStructuredNode:
    impl_id = "cognitive.structured"
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"package_state", "context", "execution"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        binding_payload = _model_operation_payload(context.bindings)
        if binding_payload.get("operation") != "structured_json":
            raise RuntimeKernelError("cognitive.structured requires operation=structured_json")
        schema = dict(binding_payload.get("output_schema") or {})
        compiled_schema = compile_json_schema(
            schema=schema,
            model_name=_model_name(context.node_id),
        )
        model_role = _model_role_from_payload(binding_payload, default="main")
        service = _model_operation_service(context)
        result = service.structured_json(
            output_model=compiled_schema.pydantic_model,
            state=state,
            prompt_binding=_prompt_binding_payload(context, binding_payload.get("prompt_id")),
            messages=context.graph_messages,
            structured_method=binding_payload.get("structured_method"),
            max_attempts=int(binding_payload.get("max_attempts") or 1),
            emit_event=context.emit_event,
            operation_metadata={"node_id": context.node_id},
            services=context.services,
            node_id=context.node_id,
            model_role=model_role,
        )
        output = result.model_dump(mode="json")
        compiled_schema.validate(output)
        return {
            **_write_output_patch(
                state=state,
                context=context,
                write_target=dict(binding_payload.get("write_target") or {}),
                output=output,
            ),
            "execution": {
                "current_node": context.node_id,
                "route_decision": "model.structured_completed",
            },
        }


def _model_operation_payload(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    for binding in bindings:
        if binding.get("binding_type") == "model_operation":
            return dict(binding.get("payload") or {})
    raise RuntimeKernelError("cognitive.structured requires a model_operation binding")


def _prompt_binding_payload(context: NodeExecutionContext, prompt_id: Any) -> dict[str, Any] | None:
    bindings = list(context.bindings)
    if prompt_id:
        requested = str(prompt_id)
        for binding in [*bindings, *context.all_bindings]:
            if binding.get("binding_type") != "prompt":
                continue
            payload = dict(binding.get("payload") or {})
            if payload.get("prompt_id") == requested:
                return payload
        raise RuntimeKernelError(f"cognitive.structured prompt binding not found: {requested}")
    for binding in bindings:
        if binding.get("binding_type") == "prompt":
            return dict(binding.get("payload") or {})
    return None


def _model_operation_service(context: NodeExecutionContext):
    service = context.services.model_operation_service
    if service is None:
        raise RuntimeKernelError("cognitive.structured requires model_operation_service")
    return service


def _model_role_from_payload(payload: dict[str, Any], *, default: ModelRole) -> ModelRole:
    value = str(payload.get("model_role") or default).strip()
    if value not in {"main", "task", "compression"}:
        raise RuntimeKernelError(f"unsupported model_operation.model_role: {value}")
    return cast(ModelRole, value)


def _write_output_patch(
    *,
    state: RuntimeState,
    context: NodeExecutionContext,
    write_target: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    section = str(write_target.get("section") or "")
    if section == "context":
        return {"context": {"model_outputs": {context.node_id: output}}}
    if section != "package_state":
        raise RuntimeKernelError(f"unsupported model_operation write_target.section: {section}")
    namespace = str(write_target.get("namespace") or "").strip()
    if not namespace:
        raise RuntimeKernelError("package_state write_target requires namespace")
    namespace_state = deepcopy(state.package_state.get(namespace) or {})
    if not isinstance(namespace_state, dict):
        raise RuntimeKernelError(f"package_state namespace is not an object: {namespace}")
    path = [str(item) for item in (write_target.get("path") or [])]
    updated = _deep_set(namespace_state, path, output) if path else output
    if not isinstance(updated, dict):
        raise RuntimeKernelError("package_state structured output must write an object")
    return {"package_state": {namespace: updated}}


def _deep_set(base: dict[str, Any], path: list[str], value: dict[str, Any]) -> dict[str, Any]:
    cursor: dict[str, Any] = base
    for segment in path[:-1]:
        current = cursor.get(segment)
        if current is None:
            current = {}
            cursor[segment] = current
        if not isinstance(current, dict):
            raise RuntimeKernelError(f"cannot write structured output through non-object path segment: {segment}")
        cursor = current
    cursor[path[-1]] = value
    return base


def _model_name(node_id: str) -> str:
    return "StructuredOutput_" + "".join(ch if ch.isalnum() else "_" for ch in node_id)
