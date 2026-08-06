from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_kernel.state import PlanEvent, PlanState, PlanStep, RuntimeState


RUNTIME_PLAN_TOOL_ID = "runtime_plan"
PLAN_AND_EXECUTE_PATTERN_ID = "plan_and_execute"


def is_plan_and_execute_pattern_id(pattern_id: str | None) -> bool:
    value = str(pattern_id or "").strip()
    if value == PLAN_AND_EXECUTE_PATTERN_ID:
        return True
    namespace, separator, base_pattern_id = value.rpartition("__")
    return bool(separator and namespace and base_pattern_id == PLAN_AND_EXECUTE_PATTERN_ID)


PlanAction = Literal[
    "inspect",
    "create_plan",
    "start_step",
    "complete_step",
    "fail_step",
    "skip_step",
    "add_step",
    "revise_step",
    "complete_plan",
    "fail_plan",
]


class RuntimePlanStepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="Short outcome-oriented plan step title. Do not name the step after a tool call.")
    objective: str = Field(description="What this step should understand, decide, produce, or verify for the user.")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Step ids that must be completed before this step can be started.",
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Concrete evidence or output that lets the executor know this step is complete.",
    )
    tool_hints: list[str] = Field(
        default_factory=list,
        description="Optional tool ids that may help; tools are implementation hints, not the plan objective.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimePlanToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: PlanAction
    goal: str | None = None
    steps: list[RuntimePlanStepInput] = Field(default_factory=list)
    step: RuntimePlanStepInput | None = None
    step_id: str | None = None
    title: str | None = None
    objective: str | None = None
    acceptance_criteria: list[str] | None = None
    tool_hints: list[str] | None = None
    result_summary: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    reason: str = ""
    recoverable: bool = True


class RuntimePlanToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: PlanState
    status: Literal["completed", "execution_failed"] = "completed"
    message: str


def runtime_plan_model_tool() -> StructuredTool:
    def _placeholder(**_kwargs: Any) -> dict[str, Any]:
        return {
            "type": "tool_observation",
            "status": "execution_failed",
            "tool_id": RUNTIME_PLAN_TOOL_ID,
            "message": "runtime_plan is handled by RuntimeKernel tool_exec and cannot run outside a runtime graph.",
            "retryable": False,
        }

    return StructuredTool.from_function(
        func=_placeholder,
        name=RUNTIME_PLAN_TOOL_ID,
        description=(
            "Manage the current run's dynamic plan state. Create outcome-oriented plan steps before execution. "
            "A plan step should describe an analytical, verification, construction, or delivery objective; "
            "do not make steps merely a list of tool calls. Put useful tool ids in tool_hints. "
            "Use it to inspect, create, start, complete, fail, skip, add, revise, complete, or fail plan steps. "
            "Do not write the whole plan state directly."
        ),
        args_schema=RuntimePlanToolInput,
        infer_schema=False,
        metadata={"agent_factory": {"tool_id": RUNTIME_PLAN_TOOL_ID, "concurrent": False}},
    )


def execute_runtime_plan_action(state: RuntimeState, arguments: dict[str, Any]) -> RuntimePlanToolResult:
    try:
        request = RuntimePlanToolInput.model_validate(arguments)
        plan = _apply_action(state.plan.model_copy(deep=True), request)
        return RuntimePlanToolResult(plan=plan, message=_summary(plan))
    except Exception as exc:
        return RuntimePlanToolResult(
            plan=state.plan,
            status="execution_failed",
            message=f"{type(exc).__name__}: {exc}",
        )


def _apply_action(plan: PlanState, request: RuntimePlanToolInput) -> PlanState:
    action = request.action
    if action == "inspect":
        return plan
    if action == "create_plan":
        return _create_plan(request)
    if action == "add_step":
        return _add_step(plan, request)
    if action == "revise_step":
        return _revise_step(plan, request)
    if action == "start_step":
        return _start_step(plan, request.step_id, reason=request.reason)
    if action == "complete_step":
        return _complete_step(plan, request)
    if action == "fail_step":
        return _fail_step(plan, request)
    if action == "skip_step":
        return _skip_step(plan, request)
    if action == "complete_plan":
        return _finish_plan(plan, status="completed", reason=request.reason)
    if action == "fail_plan":
        return _finish_plan(plan, status="failed", reason=request.reason)
    raise ValueError(f"unsupported plan action: {action}")


def _create_plan(request: RuntimePlanToolInput) -> PlanState:
    goal = (request.goal or "").strip()
    if not goal:
        raise ValueError("create_plan requires goal")
    if not request.steps:
        raise ValueError("create_plan requires at least one step")
    now = _now()
    steps = [
        PlanStep(
            step_id=f"step_{index}",
            title=_required_text(step.title, "step.title"),
            objective=_required_text(step.objective, "step.objective"),
            status="in_progress" if index == 1 else "pending",
            depends_on=list(step.depends_on),
            acceptance_criteria=list(step.acceptance_criteria),
            tool_hints=list(step.tool_hints),
            created_by="planner",
            updated_at=now,
            metadata=dict(step.metadata),
        )
        for index, step in enumerate(request.steps, start=1)
    ]
    plan = PlanState(
        goal=goal,
        status="active",
        current_step_id=steps[0].step_id,
        steps=steps,
        events=[
            _event("created", reason=request.reason, payload={"goal": goal, "step_count": len(steps)}),
            _event("step_started", step_id=steps[0].step_id, reason="initial step"),
        ],
    )
    return plan


def _add_step(plan: PlanState, request: RuntimePlanToolInput) -> PlanState:
    _require_active_plan(plan)
    source = request.step
    if source is None:
        source = RuntimePlanStepInput(
            title=_required_text(request.title, "title"),
            objective=_required_text(request.objective, "objective"),
            acceptance_criteria=list(request.acceptance_criteria or []),
            tool_hints=list(request.tool_hints or []),
            metadata=dict(request.metadata or {}),
        )
    step = PlanStep(
        step_id=_next_step_id(plan),
        title=_required_text(source.title, "step.title"),
        objective=_required_text(source.objective, "step.objective"),
        depends_on=list(source.depends_on),
        acceptance_criteria=list(source.acceptance_criteria),
        tool_hints=list(source.tool_hints),
        created_by="runtime_plan",
        updated_at=_now(),
        metadata=dict(source.metadata),
    )
    plan.steps.append(step)
    plan.events.append(_event("step_added", step_id=step.step_id, reason=request.reason, payload=_step_summary(step)))
    if plan.current_step_id is None:
        return _start_step(plan, step.step_id, reason="new step added")
    return plan


def _revise_step(plan: PlanState, request: RuntimePlanToolInput) -> PlanState:
    _require_active_plan(plan)
    step = _step(plan, request.step_id)
    if request.title is not None:
        step.title = _required_text(request.title, "title")
    if request.objective is not None:
        step.objective = _required_text(request.objective, "objective")
    if request.acceptance_criteria is not None:
        step.acceptance_criteria = list(request.acceptance_criteria)
    if request.tool_hints is not None:
        step.tool_hints = list(request.tool_hints)
    if request.metadata is not None:
        step.metadata = {**step.metadata, **request.metadata}
    step.updated_at = _now()
    plan.events.append(_event("step_revised", step_id=step.step_id, reason=request.reason, payload=_step_summary(step)))
    return plan


def _start_step(plan: PlanState, step_id: str | None, *, reason: str = "") -> PlanState:
    _require_active_plan(plan)
    target = _step(plan, step_id or plan.current_step_id or _next_pending_step_id(plan))
    if target.status not in {"pending", "in_progress"}:
        raise ValueError(f"cannot start step with status {target.status}: {target.step_id}")
    for item in plan.steps:
        if item.status == "in_progress" and item.step_id != target.step_id:
            item.status = "pending"
            item.updated_at = _now()
    target.status = "in_progress"
    target.updated_at = _now()
    plan.current_step_id = target.step_id
    plan.events.append(_event("step_started", step_id=target.step_id, reason=reason))
    return plan


def _complete_step(plan: PlanState, request: RuntimePlanToolInput) -> PlanState:
    _require_active_plan(plan)
    step = _step(plan, request.step_id or plan.current_step_id)
    if step.status not in {"pending", "in_progress"}:
        raise ValueError(f"cannot complete step with status {step.status}: {step.step_id}")
    step.status = "completed"
    step.result_summary = request.result_summary or step.result_summary
    step.evidence = [*step.evidence, *request.evidence]
    step.updated_at = _now()
    plan.last_execution = {
        "step_id": step.step_id,
        "status": "completed",
        "result_summary": step.result_summary,
        "evidence": request.evidence,
    }
    plan.events.append(_event("step_completed", step_id=step.step_id, reason=request.reason, payload={"result_summary": step.result_summary}))
    next_step_id = _next_pending_step_id(plan)
    if next_step_id is None:
        plan.current_step_id = None
        plan.status = "completed"
        plan.events.append(_event("plan_completed", reason="all steps completed"))
        return plan
    return _start_step(plan, next_step_id, reason="next pending step")


def _fail_step(plan: PlanState, request: RuntimePlanToolInput) -> PlanState:
    _require_active_plan(plan)
    step = _step(plan, request.step_id or plan.current_step_id)
    step.status = "failed"
    step.result_summary = request.result_summary or step.result_summary
    step.evidence = [*step.evidence, *request.evidence]
    step.updated_at = _now()
    plan.last_execution = {
        "step_id": step.step_id,
        "status": "failed",
        "result_summary": step.result_summary,
        "evidence": request.evidence,
    }
    plan.events.append(_event("step_failed", step_id=step.step_id, reason=request.reason, payload={"recoverable": request.recoverable}))
    if not request.recoverable:
        plan.status = "failed"
        plan.current_step_id = None
        plan.events.append(_event("plan_failed", reason=request.reason or "step failed"))
    return plan


def _skip_step(plan: PlanState, request: RuntimePlanToolInput) -> PlanState:
    _require_active_plan(plan)
    step = _step(plan, request.step_id)
    if step.status in {"completed", "failed"}:
        raise ValueError(f"cannot skip step with status {step.status}: {step.step_id}")
    step.status = "skipped"
    step.updated_at = _now()
    plan.events.append(_event("step_skipped", step_id=step.step_id, reason=request.reason))
    if plan.current_step_id == step.step_id:
        next_step_id = _next_pending_step_id(plan)
        if next_step_id is None:
            plan.current_step_id = None
            plan.status = "completed"
            plan.events.append(_event("plan_completed", reason="no pending steps remain"))
        else:
            _start_step(plan, next_step_id, reason="current step skipped")
    return plan


def _finish_plan(plan: PlanState, *, status: Literal["completed", "failed"], reason: str) -> PlanState:
    if plan.status == "empty":
        raise ValueError("cannot finish an empty plan")
    plan.status = status
    plan.current_step_id = None
    plan.events.append(_event("plan_completed" if status == "completed" else "plan_failed", reason=reason))
    return plan


def _require_active_plan(plan: PlanState) -> None:
    if plan.status != "active":
        raise ValueError(f"plan is not active: {plan.status}")


def _step(plan: PlanState, step_id: str | None) -> PlanStep:
    value = (step_id or "").strip()
    if not value:
        raise ValueError("step_id is required")
    for step in plan.steps:
        if step.step_id == value:
            return step
    raise ValueError(f"unknown step_id: {value}")


def _next_pending_step_id(plan: PlanState) -> str | None:
    completed = {step.step_id for step in plan.steps if step.status in {"completed", "skipped"}}
    for step in plan.steps:
        if step.status != "pending":
            continue
        if any(dep not in completed for dep in step.depends_on):
            continue
        return step.step_id
    return None


def _next_step_id(plan: PlanState) -> str:
    index = len(plan.steps) + 1
    existing = {step.step_id for step in plan.steps}
    while f"step_{index}" in existing:
        index += 1
    return f"step_{index}"


def _event(kind: str, *, step_id: str | None = None, reason: str = "", payload: dict[str, Any] | None = None) -> PlanEvent:
    return PlanEvent(
        event_id=uuid4().hex,
        kind=kind,
        step_id=step_id,
        reason=reason,
        payload=payload or {},
        created_at=_now(),
    )


def _summary(plan: PlanState) -> str:
    counts: dict[str, int] = {}
    for step in plan.steps:
        counts[step.status] = counts.get(step.status, 0) + 1
    parts = [f"{key}={value}" for key, value in sorted(counts.items())]
    current = f", current={plan.current_step_id}" if plan.current_step_id else ""
    return f"Plan {plan.status}{current}; " + (", ".join(parts) if parts else "no steps")


def _step_summary(step: PlanStep) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "title": step.title,
        "objective": step.objective,
        "status": step.status,
    }


def _required_text(value: str | None, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
