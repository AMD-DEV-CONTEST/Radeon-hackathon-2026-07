"""Execute raw Agent cases and record measured outcomes without prefilled success."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import orjson
from pydantic import Field

from buildguard.agent.graph import BuildGuardAgent
from buildguard.agent.nodes.executor import Tool
from buildguard.config import Settings
from buildguard.llm.base import LocalLLMBackend
from buildguard.schemas.common import StrictSchema


class AgentCaseInput(StrictSchema):
    case_id: str = Field(min_length=1, max_length=256)
    input: str = Field(min_length=1, max_length=100_000)
    expected_tools: list[str] = Field(default_factory=list)
    expected_order: list[str] = Field(default_factory=list)
    expected_arguments: list[dict[str, Any]] = Field(default_factory=list)
    expected_confirmation: bool = False
    expected_outcome: str = "completed"
    follow_up_inputs: list[str] = Field(default_factory=list)


class AgentCaseResult(StrictSchema):
    case_id: str
    task_succeeded: bool
    expected_tools: list[str]
    selected_tools: list[str]
    expected_arguments: list[dict[str, Any]]
    actual_arguments: list[dict[str, Any]]
    planned_steps: int = Field(ge=0)
    completed_steps: int = Field(ge=0)
    expected_confirmation: bool
    actual_confirmation: bool
    replan_required: bool
    replan_succeeded: bool
    multi_turn: bool
    multi_turn_succeeded: bool
    duplicate_tool_calls: int = Field(ge=0)
    failure_reason: str | None = None


class AgentHarnessSummary(StrictSchema):
    total_cases: int = Field(ge=0)
    executed_cases: int = Field(ge=0)
    resumed_cases: int = Field(ge=0)
    succeeded_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    result_path: Path


def _read_jsonl(path: Path, schema: type[StrictSchema]) -> list[StrictSchema]:
    records: list[StrictSchema] = []
    for line_number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            records.append(schema.model_validate(orjson.loads(raw)))
        except (orjson.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid JSONL record at line {line_number}: {exc}") from exc
    return records


class AgentExecutionHarness:
    def __init__(
        self,
        settings: Settings,
        backend: LocalLLMBackend,
        tools: dict[str, Tool] | None = None,
    ) -> None:
        self.settings = settings
        self.backend = backend
        if settings.app.environment == "competition" and tools is None:
            raise ValueError("Competition Agent harness requires production tools")
        self.tools = tools

    def _execute(self, case: AgentCaseInput) -> AgentCaseResult:
        agent = BuildGuardAgent(
            self.backend,
            self.settings.app.agent,
            self.tools,
        )
        state = agent.chat(case.input, session_id=f"evaluation-{case.case_id}")
        actual_confirmation = state["status"] == "WAIT_FOR_CONFIRMATION"
        if actual_confirmation:
            state = agent.confirm(state["task_id"], approved=True)
        first_turn_succeeded = state["status"] == case.expected_outcome
        multi_turn_succeeded = not case.follow_up_inputs
        for follow_up in case.follow_up_inputs:
            follow_state = agent.chat(follow_up, session_id=state["session_id"])
            if follow_state["status"] == "WAIT_FOR_CONFIRMATION":
                follow_state = agent.confirm(follow_state["task_id"], approved=True)
            multi_turn_succeeded = follow_state["status"] == case.expected_outcome
            state = follow_state

        plan = state["plan"]
        steps = plan.steps if plan is not None else []
        selected = [step.tool_name for step in steps if step.tool_name is not None]
        arguments = [step.arguments for step in steps if step.tool_name is not None]
        counts = Counter(selected)
        duplicate_calls = sum(count - 1 for count in counts.values() if count > 1)
        expected_order = case.expected_order or case.expected_tools
        tools_match = selected == expected_order
        arguments_match = (
            not case.expected_arguments or arguments == case.expected_arguments
        )
        confirmation_match = actual_confirmation == case.expected_confirmation
        succeeded = (
            first_turn_succeeded
            and multi_turn_succeeded
            and tools_match
            and arguments_match
            and confirmation_match
        )
        failures: list[str] = []
        if not first_turn_succeeded:
            failures.append(f"outcome={state['status']!r}")
        if not tools_match:
            failures.append("tool order mismatch")
        if not arguments_match:
            failures.append("tool arguments mismatch")
        if not confirmation_match:
            failures.append("confirmation mismatch")
        failures.extend(state["errors"])
        return AgentCaseResult(
            case_id=case.case_id,
            task_succeeded=succeeded,
            expected_tools=case.expected_tools,
            selected_tools=selected,
            expected_arguments=case.expected_arguments,
            actual_arguments=arguments,
            planned_steps=len(steps),
            completed_steps=sum(result.success for result in state["tool_results"]),
            expected_confirmation=case.expected_confirmation,
            actual_confirmation=actual_confirmation,
            replan_required=state["retry_count"] > 0,
            replan_succeeded=state["retry_count"] > 0 and state["status"] == "completed",
            multi_turn=bool(case.follow_up_inputs),
            multi_turn_succeeded=multi_turn_succeeded,
            duplicate_tool_calls=duplicate_calls,
            failure_reason="; ".join(failures) if failures else None,
        )

    def run(
        self, cases_path: Path, result_path: Path, *, resume: bool = True
    ) -> AgentHarnessSummary:
        cases = [
            AgentCaseInput.model_validate(item)
            for item in _read_jsonl(cases_path.resolve(), AgentCaseInput)
        ]
        result = result_path.resolve()
        result.parent.mkdir(parents=True, exist_ok=True)
        existing: list[AgentCaseResult] = []
        if resume and result.is_file():
            existing = [
                AgentCaseResult.model_validate(item)
                for item in _read_jsonl(result, AgentCaseResult)
            ]
        completed = {item.case_id for item in existing}
        executed: list[AgentCaseResult] = []
        with result.open("ab") as stream:
            for case in cases:
                if case.case_id in completed:
                    continue
                try:
                    record = self._execute(case)
                except (OSError, RuntimeError, ValueError, KeyError) as exc:
                    record = AgentCaseResult(
                        case_id=case.case_id,
                        task_succeeded=False,
                        expected_tools=case.expected_tools,
                        selected_tools=[],
                        expected_arguments=case.expected_arguments,
                        actual_arguments=[],
                        planned_steps=0,
                        completed_steps=0,
                        expected_confirmation=case.expected_confirmation,
                        actual_confirmation=False,
                        replan_required=False,
                        replan_succeeded=False,
                        multi_turn=bool(case.follow_up_inputs),
                        multi_turn_succeeded=False,
                        duplicate_tool_calls=0,
                        failure_reason=str(exc),
                    )
                stream.write(orjson.dumps(record.model_dump(mode="json")) + b"\n")
                stream.flush()
                executed.append(record)
        all_results = [*existing, *executed]
        return AgentHarnessSummary(
            total_cases=len(cases),
            executed_cases=len(executed),
            resumed_cases=len(existing),
            succeeded_cases=sum(item.task_succeeded for item in all_results),
            failed_cases=sum(not item.task_succeeded for item in all_results),
            result_path=result,
        )
