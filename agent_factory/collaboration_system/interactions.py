"""Public interaction projection for suspended background tasks."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.contracts import BackgroundTask


InteractionKind = Literal[
    "ask_user",
    "resource_request",
    "tool_approval",
    "publish_confirmation",
    "external_condition",
    "internal_wait",
]


class PendingInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_id: str
    kind: InteractionKind
    title: str
    message: str
    source: dict[str, str] = Field(default_factory=dict)
    options: list[dict[str, Any]] = Field(default_factory=list)
    requests: list[dict[str, Any]] = Field(default_factory=list)
    resource_requests: list[dict[str, Any]] = Field(default_factory=list)
    workspace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def project_pending_interaction(task: BackgroundTask) -> PendingInteraction | None:
    pending = task.pending_approval if task.status == "waiting_approval" else task.pending_external
    if not isinstance(pending, dict):
        return _project_publish_confirmation(task)
    interaction_id = str(pending.get("request_id") or "").strip()
    event = _mapping(pending.get("payload"))
    event_type = str(event.get("event_type") or "").strip()
    payload = _mapping(event.get("payload"))
    interrupt_type = str(payload.get("type") or "").strip()
    source = {
        "task_id": task.task_id,
        "task_type": task.type,
        **({"agent_id": task.assignee_package_id} if task.assignee_package_id else {}),
    }

    if task.status == "waiting_approval" or event_type == "tool_approval_requested":
        return PendingInteraction(
            interaction_id=interaction_id,
            kind="tool_approval",
            title=str(payload.get("title") or "工具执行需要批准"),
            message=str(payload.get("message") or "请检查工具、参数和风险后决定是否继续。"),
            source=source,
            requests=_mapping_list(payload.get("requests")),
            payload=payload,
        )

    if event_type == "waiting_for_workers":
        return PendingInteraction(
            interaction_id=interaction_id,
            kind="internal_wait",
            title="等待并行任务",
            message=str(payload.get("message") or "正在等待已启动的子 Agent 完成。"),
            source=source,
            payload=payload,
        )

    resource_requests = _mapping_list(payload.get("resource_requests"))
    if resource_requests:
        kind: InteractionKind = "resource_request"
    elif interrupt_type in {"ask_user", "create_agent_question", "agent_evolution_question"}:
        kind = "ask_user"
    elif str(payload.get("resume_kind") or "").strip() == "answer":
        kind = "ask_user"
    else:
        kind = "external_condition"
    return PendingInteraction(
        interaction_id=interaction_id,
        kind=kind,
        title=str(payload.get("title") or ("需要补充信息" if kind == "ask_user" else "等待外部条件")),
        message=str(payload.get("message") or "任务需要外部条件满足后才能继续。"),
        source=source,
        options=_mapping_list(payload.get("options")),
        resource_requests=resource_requests,
        workspace_id=_optional_text(payload.get("workspace_id")),
        payload=payload,
    )


def _project_publish_confirmation(task: BackgroundTask) -> PendingInteraction | None:
    task_type = getattr(task.type, "value", task.type)
    if task.status != "succeeded" or task_type != "manufacture":
        return None
    result = _mapping(task.result)
    runtime_event = _mapping(result.get("runtime_event"))
    runtime_payload = _mapping(runtime_event.get("payload"))
    completed_publish_state = _mapping(runtime_payload.get("publish_ready"))
    workspace_id = str(
        completed_publish_state.get("workspace_id")
        or task.assignee_session_id
        or ""
    ).strip()
    if not workspace_id:
        return None

    from agent_factory.create_agent.workspace import CreateAgentWorkspace

    try:
        publish_state = CreateAgentWorkspace.for_session(workspace_id).read_publish_report()
    except (FileNotFoundError, ValueError):
        return None
    if str(publish_state.get("status") or "").strip() != "ready":
        return None

    return PendingInteraction(
        interaction_id=f"{task.task_id}:publish:{workspace_id}",
        kind="publish_confirmation",
        title="Agent 已完成制造，等待发布",
        message=str(publish_state.get("message") or "请检查校验结果并确认是否发布。"),
        source={
            "task_id": task.task_id,
            "task_type": str(task_type),
            "workspace_id": workspace_id,
        },
        workspace_id=workspace_id,
        payload=publish_state,
    )


def public_task_payload(task: BackgroundTask) -> dict[str, Any]:
    payload = task.model_dump(mode="json", exclude={"pending_approval", "pending_external", "resume_payload"})
    interaction = project_pending_interaction(task)
    payload["pending_interaction"] = interaction.model_dump(mode="json") if interaction else None
    return payload


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
