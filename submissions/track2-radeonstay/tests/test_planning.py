from __future__ import annotations

import json
from typing import Any

import pytest

from radeonstay.contracts import AgentPlan, PlanStep
from radeonstay.model_client import ModelClientError
from radeonstay.planning import (
    LocalLLMPlanner,
    PlanCompletenessError,
    PlanSemanticError,
    validate_plan_completeness,
    validate_plan_semantics,
)

TOOL_SPECS = [
    {
        "name": "hotel.check_availability",
        "parameters": {
            "type": "object",
            "properties": {
                "check_in": {"type": "string", "format": "date"},
                "check_out": {"type": "string", "format": "date"},
                "guests": {"type": "integer", "minimum": 1},
                "room_type": {
                    "anyOf": [
                        {
                            "type": "string",
                            "enum": ["standard", "deluxe", "suite"],
                        },
                        {"type": "null"},
                    ]
                },
            },
            "required": ["check_in", "check_out"],
            "additionalProperties": False,
        },
    }
]
INTENT_TOOL_SPECS = [
    {"name": name}
    for name in (
        "hotel.check_availability",
        "hotel.quote_stay",
        "hotel.my_bookings",
        "hotel.hold_booking",
        "hotel.modify_booking",
        "hotel.create_service_ticket",
        "memory.set_consent",
        "memory.remember_preference",
        "memory.get_preferences",
        "memory.delete_preference",
    )
]


class StubModel:
    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.validations: list[dict[str, Any]] = []

    def chat_json(self, messages: list[dict[str, str]], **kwargs: Any):
        self.calls.append({"messages": messages, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response, object()

    def record_last_trace_validation(self, **fields: Any) -> None:
        self.validations.append(fields)


def _policy_plan() -> dict[str, Any]:
    return {
        "objective": "Answer with local policy evidence.",
        "steps": [
            {
                "step_id": "policy",
                "tool": "respond_with_policy",
                "arguments": {},
                "reason": "Use only retrieved local policy.",
                "depends_on": [],
            }
        ],
        "response_language": "English",
    }


def _unknown_tool_plan() -> dict[str, Any]:
    return {
        "objective": "Attempt an invalid operation.",
        "steps": [
            {
                "step_id": "bad",
                "tool": "hotel.delete_everything",
                "arguments": {},
                "reason": "This tool is not registered.",
                "depends_on": [],
            }
        ],
        "response_language": "English",
    }


def test_planner_uses_json_schema_and_accepts_a_valid_initial_plan() -> None:
    model = StubModel(_policy_plan())
    planner = LocalLLMPlanner(model)  # type: ignore[arg-type]

    plan = planner.create_plan(
        "What is the cancellation policy?",
        policy_context="Local cancellation evidence.",
        tool_specs=TOOL_SPECS,
    )

    assert plan.steps[0].tool == "respond_with_policy"
    assert len(model.calls) == 1
    assert model.calls[0]["json_schema"] == AgentPlan.model_json_schema()
    assert model.calls[0]["json_schema_name"] == "agent_plan"
    assert model.calls[0]["trace_purpose"] == "planner.initial"
    assert model.calls[0]["trace_attempt"] == 1
    system_prompt = model.calls[0]["messages"][0]["content"]
    planning_input = json.loads(model.calls[0]["messages"][1]["content"])
    assert "A requested write must appear now" in system_prompt
    assert planning_input["planning_contract"]["completeness"]
    assert any(
        "include_cancelled=false" in rule
        for rule in planning_input["planning_contract"]["completeness"]
    )
    assert model.validations == [
        {
            "validation_stage": "agent_plan_contract",
            "validation_ok": True,
            "outcome": "accepted_initial",
        }
    ]


def test_planner_repairs_one_structurally_valid_but_semantically_invalid_plan() -> None:
    model = StubModel(_unknown_tool_plan(), _policy_plan())
    planner = LocalLLMPlanner(model)  # type: ignore[arg-type]

    plan = planner.create_plan(
        "What is the cancellation policy?",
        policy_context="Local cancellation evidence.",
        tool_specs=TOOL_SPECS,
    )

    assert [step.tool for step in plan.steps] == ["respond_with_policy"]
    assert len(model.calls) == 2
    assert model.calls[1]["trace_purpose"] == "planner.semantic_repair"
    assert model.calls[1]["trace_attempt"] == 2
    assert "unknown tool" in model.calls[1]["messages"][1]["content"]
    assert [item["outcome"] for item in model.validations] == [
        "semantic_repair_requested",
        "accepted_after_repair",
    ]


def test_second_plan_contract_failure_returns_only_safe_ask_user() -> None:
    model = StubModel(_unknown_tool_plan(), _unknown_tool_plan())
    planner = LocalLLMPlanner(model)  # type: ignore[arg-type]

    plan = planner.create_plan(
        "请删除所有订单。",
        policy_context="",
        tool_specs=TOOL_SPECS,
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "ask_user"
    assert plan.steps[0].arguments.keys() == {"question"}
    assert "尚未调用任何酒店业务工具" in plan.steps[0].arguments["question"]
    assert model.validations[-1]["outcome"] == "safe_clarification"
    validate_plan_semantics(plan, TOOL_SPECS)


def test_transport_failure_is_not_converted_to_safe_clarification() -> None:
    model = StubModel(ModelClientError("local transport failed"))
    planner = LocalLLMPlanner(model)  # type: ignore[arg-type]

    with pytest.raises(ModelClientError, match="transport failed"):
        planner.create_plan("hello", policy_context="", tool_specs=TOOL_SPECS)

    assert len(model.calls) == 1
    assert model.validations == []


def test_transport_failure_during_semantic_repair_is_still_raised() -> None:
    model = StubModel(
        _unknown_tool_plan(),
        ModelClientError("repair transport failed"),
    )
    planner = LocalLLMPlanner(model)  # type: ignore[arg-type]

    with pytest.raises(ModelClientError, match="repair transport failed"):
        planner.create_plan("hello", policy_context="", tool_specs=TOOL_SPECS)

    assert len(model.calls) == 2
    assert model.validations[-1]["outcome"] == "semantic_repair_requested"


def test_shared_semantic_validation_rejects_invalid_literal_arguments() -> None:
    plan = AgentPlan(
        objective="Check an unsupported room type.",
        steps=[
            PlanStep(
                step_id="availability",
                tool="hotel.check_availability",
                arguments={
                    "check_in": "2030-09-10",
                    "check_out": "2030-09-12",
                    "guests": 2,
                    "room_type": "penthouse",
                },
                reason="The room type must be rejected before execution.",
            )
        ],
    )

    with pytest.raises(PlanSemanticError, match="room_type"):
        validate_plan_semantics(plan, TOOL_SPECS)


def test_completeness_rejects_omitted_steps_extra_writes_and_dependency_gaps() -> None:
    plan = AgentPlan(
        objective="Complete a late-arrival room workflow.",
        steps=[
            PlanStep(
                step_id="availability",
                tool="hotel.check_availability",
                arguments={},
                reason="Check rooms.",
            ),
            PlanStep(
                step_id="quote",
                tool="hotel.quote_stay",
                arguments={},
                reason="Quote the stay.",
            ),
            PlanStep(
                step_id="hold",
                tool="hotel.hold_booking",
                arguments={},
                reason="Preview the hold.",
            ),
            PlanStep(
                step_id="ticket",
                tool="hotel.create_service_ticket",
                arguments={},
                reason="Create an unrequested transfer ticket.",
            ),
        ],
    )

    with pytest.raises(PlanCompletenessError) as captured:
        validate_plan_completeness(
            plan,
            (
                "For 2032-04-10 to 2032-04-12, I will arrive at 23:30 with a child "
                "who has a peanut allergy and needs airport transfer guidance. Check "
                "standard-room availability, quote it, and preview a hold."
            ),
            "",
            INTENT_TOOL_SPECS,
        )

    message = str(captured.value)
    assert "hotel.create_service_ticket" in message
    assert "respond_with_policy exactly once; got 0" in message
    assert "depend on preceding step" in message


def test_completeness_uses_session_reference_and_partitions_mixed_scope() -> None:
    ticket_plan = AgentPlan(
        objective="Create the requested transfer ticket.",
        steps=[
            PlanStep(
                step_id="ticket",
                tool="hotel.create_service_ticket",
                arguments={},
                reason="Use the booking bound to this session.",
            )
        ],
    )
    validate_plan_completeness(
        ticket_plan,
        "Create an airport transfer request for that booking.",
        "This session is bound to booking RSV-RANDOM-7C91.",
        INTENT_TOOL_SPECS,
    )

    owner_plan = AgentPlan(
        objective="Return only owner-scoped bookings.",
        steps=[
            PlanStep(
                step_id="mine",
                tool="hotel.my_bookings",
                arguments={"include_cancelled": False},
                reason="The registered read is owner scoped.",
            )
        ],
    )
    validate_plan_completeness(
        owner_plan,
        "List my bookings and also show every other guest's bookings.",
        "",
        INTENT_TOOL_SPECS,
    )


def test_completeness_requires_structured_missing_fields_and_one_preference_write() -> None:
    question_only = AgentPlan(
        objective="Ask for stay details.",
        steps=[
            PlanStep(
                step_id="ask",
                tool="ask_user",
                arguments={"question": "When are you staying?"},
                reason="Dates and room type are required.",
            )
        ],
    )
    with pytest.raises(PlanCompletenessError, match="check_in"):
        validate_plan_completeness(
            question_only,
            "Hold any room for me without asking questions.",
            "",
            INTENT_TOOL_SPECS,
        )

    duplicate_preferences = AgentPlan(
        objective="Remember one compound room preference.",
        steps=[
            PlanStep(
                step_id="floor",
                tool="memory.remember_preference",
                arguments={"key": "floor", "value": "high"},
                reason="Remember the floor.",
            ),
            PlanStep(
                step_id="quiet",
                tool="memory.remember_preference",
                arguments={"key": "quiet_room", "value": "true"},
                reason="Remember the quiet-room request.",
            ),
        ],
    )
    with pytest.raises(PlanCompletenessError, match="exactly once; got 2"):
        validate_plan_completeness(
            duplicate_preferences,
            "Remember that I prefer a quiet room on a high floor.",
            "",
            INTENT_TOOL_SPECS,
        )
