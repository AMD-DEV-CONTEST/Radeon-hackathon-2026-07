from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


RUNTIME_RENDER_PROTOCOL_VERSION = "runtime_render.v1"

RuntimeRenderEventType = Literal["node_started", "node_progress", "node_completed", "node_failed"]
RuntimeRenderProducer = Literal["factory", "agent"]
RuntimeRenderSeverity = Literal["info", "warning", "error"]


PLAN_AND_EXECUTE_MODEL_MESSAGE_NODES = frozenset({"casual_react", "executor", "final_answer"})
PLAN_AND_EXECUTE_FLOW_NODES = PLAN_AND_EXECUTE_MODEL_MESSAGE_NODES | frozenset({"tool_exec"})
MODEL_MESSAGE_INTERNAL_NODES = frozenset({"factory_tools", "ingress", "intent_gate", "tool_exec", "commit", "finalize"})


class NodeRenderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    label: str
    kind: str
    purpose: str
    doing: str
    expected_output: str
    visible_to_user: bool = True


class RuntimeRenderEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    protocol_version: Literal["runtime_render.v1"] = RUNTIME_RENDER_PROTOCOL_VERSION
    event_type: RuntimeRenderEventType
    producer_type: RuntimeRenderProducer
    session_id: str | None = None
    thread_id: str | None = None
    run_id: str | None = None
    graph_id: str
    stage_id: str | None = None
    node_id: str
    node_label: str
    node_kind: str
    span_id: str | None = None
    parent_span_id: str | None = None
    sequence: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    severity: RuntimeRenderSeverity = "info"
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RenderManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["render_manifest.v0"] = "render_manifest.v0"
    graph_id: str
    producer_type: Literal["agent"] = "agent"
    nodes: dict[str, NodeRenderSpec] = Field(default_factory=dict)


class RenderManifestValidationError(ValueError):
    pass


def validate_render_manifest(manifest: RenderManifest, node_ids: set[str]) -> RenderManifest:
    errors: list[str] = []
    manifest_node_ids = set(manifest.nodes)
    for node_id in sorted(node_ids - manifest_node_ids):
        errors.append(f"render_manifest missing node_id: {node_id}")
    for node_id in sorted(manifest_node_ids - node_ids):
        errors.append(f"render_manifest contains unknown node_id: {node_id}")
    for key, spec in manifest.nodes.items():
        if spec.node_id != key:
            errors.append(f"render_manifest node key mismatch: {key} != {spec.node_id}")
        for field_name in ("label", "kind", "purpose", "doing", "expected_output"):
            value = getattr(spec, field_name)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"render_manifest.{key}.{field_name} must not be empty")
    if errors:
        raise RenderManifestValidationError("; ".join(errors))
    return manifest


def default_node_render_spec(
    *,
    node_id: str,
    node_type: str,
    impl: str,
    pattern_id: str = "",
) -> NodeRenderSpec:
    label = node_id.replace("_", " ").title()
    return NodeRenderSpec(
        node_id=node_id,
        label=label,
        kind=node_type,
        purpose=f"Execute runtime node {node_id}.",
        doing=f"Running implementation {impl}.",
        expected_output=f"Validated state patch from {node_id}.",
        visible_to_user=default_node_visible_to_user(pattern_id=pattern_id, node_id=node_id),
    )


def default_node_visible_to_user(*, pattern_id: str, node_id: str) -> bool:
    if pattern_id == "plan_and_execute":
        return node_id in PLAN_AND_EXECUTE_FLOW_NODES
    if node_id in {"ingress", "commit", "finalize"}:
        return False
    return True


def default_model_message_visible_to_user(*, pattern_id: str, node_id: str) -> bool:
    if pattern_id == "plan_and_execute":
        return node_id in PLAN_AND_EXECUTE_MODEL_MESSAGE_NODES
    if node_id in MODEL_MESSAGE_INTERNAL_NODES:
        return False
    return True
