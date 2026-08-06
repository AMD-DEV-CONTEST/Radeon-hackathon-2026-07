from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.trace_policy import AgentPackageExecutionError
from agent_factory.runtime_kernel.types import ToolExecutionResult
from agent_factory.tooling.schema_compiler import compile_json_schema


PACKAGE_NODE_PROVIDER_ID = "builtin.package_nodes"


class PackageNodeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_node.v0"] = "package_node.v0"
    impl_id: str
    node_type: Literal["cognitive", "operational", "governance", "terminal"]
    entrypoint: str
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "additionalProperties": True}
    )
    output_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "additionalProperties": True}
    )
    readable_sections: list[str] = Field(default_factory=list)
    writable_sections: list[str] = Field(default_factory=list)
    required_services: list[str] = Field(default_factory=list)
    tool_access: list[str] = Field(default_factory=list)
    description: str

    @field_validator("impl_id")
    @classmethod
    def _impl_id_is_package_scoped(cls, value: str) -> str:
        impl_id = value.strip()
        if not impl_id:
            raise ValueError("impl_id must not be empty")
        if not impl_id.startswith("package."):
            raise ValueError("package node impl_id must start with package.")
        return impl_id

    @field_validator("entrypoint")
    @classmethod
    def _entrypoint_is_relative_run_function(cls, value: str) -> str:
        raw = value.strip()
        if not raw:
            raise ValueError("entrypoint must not be empty")
        if ":" not in raw:
            raise ValueError("entrypoint must use path.py:run format")
        path_text, function_name = raw.split(":", 1)
        if function_name != "run":
            raise ValueError("package node entrypoint function must be run")
        path = Path(path_text)
        if path.is_absolute() or path.suffix != ".py" or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("package node entrypoint path must be a safe relative Python file")
        return raw

    @field_validator("readable_sections", "writable_sections", "required_services", "tool_access")
    @classmethod
    def _string_list_is_clean(cls, value: list[str]) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw).strip()
            if not item:
                raise ValueError("list fields must not contain empty values")
            if item not in seen:
                items.append(item)
                seen.add(item)
        return items

    @field_validator("description")
    @classmethod
    def _description_is_not_empty(cls, value: str) -> str:
        description = value.strip()
        if not description:
            raise ValueError("description must not be empty")
        return description

    @model_validator(mode="after")
    def _schemas_are_valid(self) -> "PackageNodeManifest":
        compile_json_schema(schema=self.input_schema, model_name=_schema_model_name(self.impl_id, "Input"))
        compile_json_schema(schema=self.output_schema, model_name=_schema_model_name(self.impl_id, "Output"))
        return self


@dataclass(frozen=True, slots=True)
class PackageNodeProviderFactory:
    provider_id: str = PACKAGE_NODE_PROVIDER_ID

    def build(self, *, package_root: Path, config: dict[str, Any]) -> "PackageNodeProvider":
        roots = config.get("roots", ["nodes"])
        if not isinstance(roots, list) or not roots or not all(isinstance(item, str) for item in roots):
            raise RuntimeKernelError("builtin.package_nodes roots config must be a non-empty string list")
        return PackageNodeProvider(package_root=package_root, roots=tuple(roots))


class PackageNodeProvider:
    provider_id = PACKAGE_NODE_PROVIDER_ID

    def __init__(self, *, package_root: Path, roots: tuple[str, ...]) -> None:
        self.package_root = package_root.resolve()
        self.roots = tuple(_safe_relative_path(root, field_name="package node root") for root in roots)

    def implementations(self) -> list["PackageNodeImplementation"]:
        implementations: list[PackageNodeImplementation] = []
        for root in self.roots:
            root_path = (self.package_root / root).resolve()
            _assert_inside(self.package_root, root_path, label=root)
            if not root_path.exists():
                continue
            if not root_path.is_dir():
                raise RuntimeKernelError(f"package node root is not a directory: {root}")
            for manifest_path in sorted(root_path.glob("*/manifest.json")):
                implementations.append(_load_package_node(self.package_root, manifest_path))
        return implementations


class PackageNodeImplementation:
    def __init__(
        self,
        *,
        manifest: PackageNodeManifest,
        node_dir: Path,
        entrypoint: Callable[[dict[str, Any], "NodeRuntimeContext"], dict[str, Any]],
    ) -> None:
        self.manifest = manifest
        self.node_dir = node_dir
        self._entrypoint = entrypoint
        self.impl_id = manifest.impl_id
        self.node_type = manifest.node_type
        self.supports_interrupt = False
        self.supports_subgraph_slot = False
        self.writable_sections = set(manifest.writable_sections)
        self._input_schema = compile_json_schema(
            schema=manifest.input_schema,
            model_name=_schema_model_name(manifest.impl_id, "Input"),
        )
        self._output_schema = compile_json_schema(
            schema=manifest.output_schema,
            model_name=_schema_model_name(manifest.impl_id, "Output"),
        )

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        context.services.validate_required(list(self.manifest.required_services))
        input_payload = _input_payload(state=state, context=context, manifest=self.manifest)
        try:
            self._input_schema.validate(input_payload)
        except Exception as exc:
            raise AgentPackageExecutionError(f"package node {self.impl_id} input schema validation failed: {exc}") from exc
        runtime_context = NodeRuntimeContext(
            node_id=context.node_id,
            impl_id=self.impl_id,
            resources=deepcopy(context.services.runtime_resources),
            package_state=deepcopy(state.package_state),
            runtime_config=state.runtime_config.model_dump(mode="json"),
            tool_access=tuple(self.manifest.tool_access),
            emit_event=context.emit_event,
            artifact_store=context.services.artifact_store,
            report_store=context.services.report_store,
            execute_tool_call=_tool_executor(
                impl_id=self.impl_id,
                tool_access=tuple(self.manifest.tool_access),
                tool_registry=context.services.tool_registry,
                state=state,
                emit_event=context.emit_event,
            ),
        )
        try:
            output = self._entrypoint(input_payload, runtime_context)
        except Exception as exc:
            raise AgentPackageExecutionError(f"package node {self.impl_id} failed: {exc}") from exc
        if not isinstance(output, dict):
            raise AgentPackageExecutionError(f"package node {self.impl_id} output must be a dict")
        try:
            self._output_schema.validate(output)
        except Exception as exc:
            raise AgentPackageExecutionError(f"package node {self.impl_id} output schema validation failed: {exc}") from exc
        return output


@dataclass(frozen=True, slots=True)
class NodeRuntimeContext:
    node_id: str
    impl_id: str
    resources: dict[str, Any]
    package_state: dict[str, Any]
    runtime_config: dict[str, Any]
    tool_access: tuple[str, ...]
    emit_event: Callable[[dict[str, Any]], None]
    artifact_store: Any | None
    report_store: Any | None
    execute_tool_call: Callable[[str, dict[str, Any]], dict[str, Any]]

    def write_artifact_json(
        self,
        *,
        kind: str,
        relative_path: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.artifact_store is None:
            raise RuntimeKernelError("artifact_store service is not available")
        return self.artifact_store.write_json(
            kind=kind,
            relative_path=relative_path,
            payload=payload,
            metadata=metadata,
        )

    def write_artifact_text(
        self,
        *,
        kind: str,
        relative_path: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.artifact_store is None:
            raise RuntimeKernelError("artifact_store service is not available")
        return self.artifact_store.write_text(
            kind=kind,
            relative_path=relative_path,
            content=content,
            metadata=metadata,
        )

    def write_report(
        self,
        *,
        report_id: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.report_store is None:
            raise RuntimeKernelError("report_store service is not available")
        return self.report_store.write_report(report_id=report_id, payload=payload, metadata=metadata)

    def execute_tool(self, *, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.execute_tool_call(tool_id, arguments)


def _tool_executor(
    *,
    impl_id: str,
    tool_access: tuple[str, ...],
    tool_registry: Any | None,
    state: RuntimeState,
    emit_event: Callable[[dict[str, Any]], None],
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    def execute(tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_call_id = f"package_{uuid4().hex}"
        if tool_id not in tool_access:
            _emit_tool_event(
                emit_event,
                event_type="tool_failed",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                arguments=arguments,
                status="failed",
                error=f"package node {impl_id} is not allowed to execute tool: {tool_id}",
            )
            raise RuntimeKernelError(f"package node {impl_id} is not allowed to execute tool: {tool_id}")
        if tool_registry is None or not hasattr(tool_registry, "execute"):
            _emit_tool_event(
                emit_event,
                event_type="tool_failed",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                arguments=arguments,
                status="failed",
                error="tool_registry service is not available",
            )
            raise RuntimeKernelError("tool_registry service is not available")
        _emit_tool_event(
            emit_event,
            event_type="tool_started",
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            arguments=arguments,
            status="running",
        )
        try:
            result = tool_registry.execute(tool_id, arguments, state=state)
        except Exception as exc:
            _emit_tool_event(
                emit_event,
                event_type="tool_failed",
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                arguments=arguments,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        if isinstance(result, ToolExecutionResult):
            payload = result.model_dump(mode="json")
            _emit_package_tool_result(
                emit_event=emit_event,
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                arguments=arguments,
                result=payload,
            )
            return payload
        if isinstance(result, dict):
            _emit_package_tool_result(
                emit_event=emit_event,
                tool_id=tool_id,
                tool_call_id=tool_call_id,
                arguments=arguments,
                result=result,
            )
            return result
        _emit_tool_event(
            emit_event,
            event_type="tool_failed",
            tool_id=tool_id,
            tool_call_id=tool_call_id,
            arguments=arguments,
            status="failed",
            error="tool execution result must be a ToolExecutionResult or dict",
        )
        raise RuntimeKernelError("tool execution result must be a ToolExecutionResult or dict")

    return execute


def _emit_package_tool_result(
    *,
    emit_event: Callable[[dict[str, Any]], None],
    tool_id: str,
    tool_call_id: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> None:
    status = str(result.get("status") or result.get("execution_status") or "completed")
    event_type = "tool_completed" if status == "completed" else "tool_failed"
    error = result.get("error")
    message = str(result.get("observation_summary") or result.get("message") or error or "")
    output = result.get("output") if isinstance(result.get("output"), dict) else result
    _emit_tool_event(
        emit_event,
        event_type=event_type,
        tool_id=tool_id,
        tool_call_id=tool_call_id,
        arguments=arguments,
        status="completed" if event_type == "tool_completed" else "failed",
        result=result,
        output=output,
        observation=result,
        error=None if event_type == "tool_completed" else str(error or message or "tool failed"),
        message=message,
    )


def _emit_tool_event(emit_event: Callable[[dict[str, Any]], None], **payload: Any) -> None:
    try:
        emit_event(payload)
    except Exception:
        return


def _load_package_node(package_root: Path, manifest_path: Path) -> PackageNodeImplementation:
    _assert_inside(package_root, manifest_path.resolve(), label=str(manifest_path))
    manifest = PackageNodeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    node_dir = manifest_path.parent.resolve()
    path_text, function_name = manifest.entrypoint.split(":", 1)
    entrypoint_path = (node_dir / path_text).resolve()
    _assert_inside(package_root, entrypoint_path, label=manifest.entrypoint)
    if not entrypoint_path.is_file():
        raise RuntimeKernelError(f"package node entrypoint not found: {manifest.entrypoint}")
    entrypoint = getattr(_load_module(entrypoint_path), function_name, None)
    if not callable(entrypoint):
        raise RuntimeKernelError(f"package node entrypoint is not callable: {manifest.entrypoint}")
    _validate_entrypoint_signature(entrypoint, manifest.entrypoint)
    return PackageNodeImplementation(manifest=manifest, node_dir=node_dir, entrypoint=entrypoint)


def _load_module(path: Path) -> ModuleType:
    module_name = f"_agentfactory_package_node_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeKernelError(f"cannot load package node module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_entrypoint_signature(entrypoint: Callable[..., Any], label: str) -> None:
    signature = inspect.signature(entrypoint)
    parameters = list(signature.parameters.values())
    if len(parameters) != 2 or [item.name for item in parameters] != ["input", "context"]:
        raise RuntimeKernelError(f"package node entrypoint must accept exactly input and context parameters: {label}")
    for parameter in parameters:
        if parameter.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD:
            raise RuntimeKernelError(f"package node entrypoint uses unsupported parameter kind: {label}")


def _input_payload(*, state: RuntimeState, context: NodeExecutionContext, manifest: PackageNodeManifest) -> dict[str, Any]:
    return {
        "node": {
            "node_id": context.node_id,
            "impl_id": manifest.impl_id,
            "node_type": manifest.node_type,
            "description": manifest.description,
        },
        "conversation": state.conversation.model_dump(mode="json"),
        "context": state.context.model_dump(mode="json"),
        "package_state": deepcopy(state.package_state),
        "runtime_config": state.runtime_config.model_dump(mode="json"),
        "bindings": deepcopy(context.bindings),
    }


def _safe_relative_path(value: str, *, field_name: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise RuntimeKernelError(f"{field_name} must not be empty")
    path = Path(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeKernelError(f"{field_name} must be a safe relative path")
    return raw


def _assert_inside(root: Path, target: Path, *, label: str) -> None:
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeKernelError(f"package node path escapes package root: {label}") from exc


def _schema_model_name(impl_id: str, suffix: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in impl_id)
    return f"PackageNode_{safe}_{suffix}"
