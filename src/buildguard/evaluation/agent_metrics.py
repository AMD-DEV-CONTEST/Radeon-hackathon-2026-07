"""Deterministic Agent task and planning metrics."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from buildguard.schemas.common import StrictSchema


class AgentEvaluationCase(StrictSchema):
    case_id: str = Field(min_length=1, max_length=256)
    task_succeeded: bool
    expected_tools: list[str] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    expected_arguments: list[dict[str, Any]] = Field(default_factory=list)
    actual_arguments: list[dict[str, Any]] = Field(default_factory=list)
    planned_steps: int = Field(ge=0)
    completed_steps: int = Field(ge=0)
    replan_required: bool = False
    replan_succeeded: bool = False
    multi_turn: bool = False
    multi_turn_succeeded: bool = False

    @model_validator(mode="after")
    def completion_is_consistent(self) -> AgentEvaluationCase:
        if self.completed_steps > self.planned_steps:
            raise ValueError("completed_steps cannot exceed planned_steps")
        if len(self.expected_arguments) != len(self.expected_tools):
            raise ValueError("expected arguments must align with expected tools")
        if len(self.actual_arguments) != len(self.selected_tools):
            raise ValueError("actual arguments must align with selected tools")
        return self


class AgentMetrics(StrictSchema):
    task_success_rate: float = Field(ge=0, le=1)
    tool_selection_accuracy: float = Field(ge=0, le=1)
    argument_accuracy: float = Field(ge=0, le=1)
    plan_completion: float = Field(ge=0, le=1)
    replan_success: float = Field(ge=0, le=1)
    multi_turn_success: float = Field(ge=0, le=1)
    evaluated_cases: int = Field(ge=0)


def evaluate_agent(cases: list[AgentEvaluationCase]) -> AgentMetrics:
    count = len(cases)
    if not cases:
        return AgentMetrics(
            task_success_rate=0,
            tool_selection_accuracy=0,
            argument_accuracy=0,
            plan_completion=0,
            replan_success=0,
            multi_turn_success=0,
            evaluated_cases=0,
        )
    replans = [case for case in cases if case.replan_required]
    multi_turns = [case for case in cases if case.multi_turn]
    return AgentMetrics(
        task_success_rate=sum(case.task_succeeded for case in cases) / count,
        tool_selection_accuracy=sum(
            case.expected_tools == case.selected_tools for case in cases
        )
        / count,
        argument_accuracy=sum(
            case.expected_arguments == case.actual_arguments for case in cases
        )
        / count,
        plan_completion=sum(
            min(1.0, case.completed_steps / case.planned_steps)
            if case.planned_steps
            else float(case.completed_steps == 0)
            for case in cases
        )
        / count,
        replan_success=(
            sum(case.replan_succeeded for case in replans) / len(replans)
            if replans
            else 0
        ),
        multi_turn_success=(
            sum(case.multi_turn_succeeded for case in multi_turns) / len(multi_turns)
            if multi_turns
            else 0
        ),
        evaluated_cases=count,
    )
