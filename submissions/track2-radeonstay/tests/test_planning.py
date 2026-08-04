from __future__ import annotations

import json
import random
from datetime import date, timedelta
from typing import Any

import pytest

from radeonstay.contracts import AgentPlan, PlanStep
from radeonstay.model_client import ModelClientError
from radeonstay.planning import (
    _PLANNING_CONTRACT,
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
    assert planning_input["server_obligations"] == {
        "ordered_tools": ["respond_with_policy"],
        "missing_fields": [],
        "tool_sequence_is_exact": True,
    }
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


def test_structural_repair_receives_server_workflow_and_restores_omitted_intent() -> None:
    tool_specs = [
        {
            "name": "hotel.my_bookings",
            "effect": "read",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_cancelled": {"type": "boolean", "default": False}
                },
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "name": "hotel.modify_booking",
            "effect": "write",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string", "minLength": 1},
                    "check_out": {
                        "anyOf": [
                            {"type": "string", "format": "date"},
                            {"type": "null"},
                        ]
                    },
                },
                "required": ["booking_id"],
                "additionalProperties": False,
            },
        },
    ]
    structurally_invalid = {
        "objective": "List the booking before modifying it.",
        "steps": [
            {
                "step_id": "bookings",
                "tool": "hotel.my_bookings",
                "arguments": {"include_cancelled": False},
                "depends_on": [],
            }
        ],
        "response_language": "中文",
    }
    repaired = {
        "objective": "先查看本人订单，再预览明确要求的退房日变更。",
        "steps": [
            {
                "step_id": "bookings",
                "tool": "hotel.my_bookings",
                "arguments": {"include_cancelled": False},
                "reason": "先完成用户明确要求的本人订单查看。",
                "depends_on": [],
            },
            {
                "step_id": "modify",
                "tool": "hotel.modify_booking",
                "arguments": {
                    "booking_id": "RSV-GENERATED-6A2F",
                    "check_out": "2033-07-19",
                },
                "reason": "服务端将在实际写入前生成独立确认预览。",
                "depends_on": ["bookings"],
            },
        ],
        "response_language": "中文",
    }
    model = StubModel(structurally_invalid, repaired)
    planner = LocalLLMPlanner(model)  # type: ignore[arg-type]

    plan = planner.create_plan(
        "调出我名下的预订，再把 RSV-GENERATED-6A2F 的离店日延到 2033-07-19。",
        policy_context="",
        tool_specs=tool_specs,
    )

    assert [step.tool for step in plan.steps] == [
        "hotel.my_bookings",
        "hotel.modify_booking",
    ]
    repair_input = json.loads(model.calls[1]["messages"][1]["content"])
    directive = repair_input["repair_directive"]
    assert directive["ordered_tools"] == [
        "hotel.my_bookings",
        "hotel.modify_booking",
    ]
    assert directive["missing_fields"] == []
    assert directive["argument_contracts"]["hotel.modify_booking"]["required"] == [
        "booking_id"
    ]
    assert directive["argument_contracts"]["hotel.my_bookings"]["defaults"] == {
        "include_cancelled": False
    }
    assert len(repair_input["contract_errors"]) >= 1
    assert all("message" in error for error in repair_input["contract_errors"])
    assert "MUST equal it exactly" in model.calls[1]["messages"][0]["content"]


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


def test_semantic_validation_rejects_invalid_reference_paths_and_late_steps() -> None:
    reference_specs = [
        {
            "name": "hotel.quote_stay",
            "effect": "read",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "returns": {
                "type": "object",
                "properties": {"room_type": {"type": "string"}},
                "required": ["room_type"],
                "additionalProperties": False,
            },
        },
        {
            "name": "hotel.hold_booking",
            "effect": "write",
            "parameters": {
                "type": "object",
                "properties": {"room_type": {"type": "string"}},
                "required": ["room_type"],
                "additionalProperties": False,
            },
        },
    ]
    invalid_reference = AgentPlan(
        objective="Reject a reference path absent from the declared return schema.",
        steps=[
            PlanStep(
                step_id="quote",
                tool="hotel.quote_stay",
                reason="Produce a typed local result.",
            ),
            PlanStep(
                step_id="hold",
                tool="hotel.hold_booking",
                arguments={"room_type": "{{quote.booking_id}}"},
                reason="The output path does not exist.",
                depends_on=["quote"],
            ),
        ],
    )
    with pytest.raises(PlanSemanticError, match="unavailable output path"):
        validate_plan_semantics(invalid_reference, reference_specs)

    nonterminal_question = AgentPlan(
        objective="Stop after requesting missing data.",
        steps=[
            PlanStep(
                step_id="ask",
                tool="ask_user",
                arguments={"missing": ["check_in"]},
                reason="Request a required field.",
            ),
            PlanStep(
                step_id="availability",
                tool="hotel.check_availability",
                arguments={
                    "check_in": "2031-01-10",
                    "check_out": "2031-01-11",
                    "guests": 1,
                    "room_type": "standard",
                },
                reason="This step must not follow a clarification.",
            ),
        ],
    )
    with pytest.raises(PlanSemanticError, match="terminal"):
        validate_plan_semantics(nonterminal_question, TOOL_SPECS)


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

    invented_optional_field = AgentPlan(
        objective="Ask only for genuinely required stay details.",
        steps=[
            PlanStep(
                step_id="ask",
                tool="ask_user",
                arguments={
                    "missing": [
                        "check_in",
                        "check_out",
                        "room_type",
                        "flight_number",
                    ]
                },
                reason="Flight number is optional and must not be invented as missing.",
            )
        ],
    )
    with pytest.raises(PlanCompletenessError, match="flight_number"):
        validate_plan_completeness(
            invented_optional_field,
            "Hold any room for me without asking questions.",
            "",
            INTENT_TOOL_SPECS,
        )

    missing_booking_reference = AgentPlan(
        objective="Ask for the booking identifier required to modify a booking.",
        steps=[
            PlanStep(
                step_id="ask",
                tool="ask_user",
                arguments={"missing": ["booking_id"]},
                reason="A booking ID is required for the requested change.",
            )
        ],
    )
    validate_plan_completeness(
        missing_booking_reference,
        "请修改我的订单，把退房日期延长一天。",
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


def _plan_for_intent_tools(tools: list[str]) -> AgentPlan:
    steps: list[PlanStep] = []
    previous: str | None = None
    for index, tool in enumerate(tools):
        step_id = f"intent_{index}"
        arguments: dict[str, Any] = {}
        if tool == "ask_user":
            arguments = {"question": "Please clarify the requested operation."}
        steps.append(
            PlanStep(
                step_id=step_id,
                tool=tool,
                arguments=arguments,
                reason="Represent one explicitly requested capability.",
                depends_on=[previous] if previous is not None else [],
            )
        )
        previous = step_id
    return AgentPlan(objective="Represent the complete held-out intent.", steps=steps)


def test_held_out_intent_paraphrases_require_every_capability_without_fixture_leakage() -> None:
    rng = random.Random(0xA6D5)
    check_in = date(2032, 1, 1) + timedelta(days=rng.randint(30, 300))
    check_out = check_in + timedelta(days=rng.randint(1, 5))
    change_date = check_out + timedelta(days=rng.randint(20, 90))
    booking_id = f"RSV-HO-{rng.getrandbits(32):08X}"
    workflows = [
        (
            (
                f"我在 {check_in.isoformat()} 到 {check_out.isoformat()} 住标准房，"
                "23:30 才到并带花生过敏的孩子；帮我看看空房、算总价并先锁房。"
            ),
            [
                "respond_with_policy",
                "hotel.check_availability",
                "hotel.quote_stay",
                "hotel.hold_booking",
            ],
        ),
        (
            (
                f"From {check_in.isoformat()} to {check_out.isoformat()}, find an open "
                "standard room for a 23:30 arrival with a child who has a peanut allergy; "
                "price the stay and tentatively lock it."
            ),
            [
                "respond_with_policy",
                "hotel.check_availability",
                "hotel.quote_stay",
                "hotel.hold_booking",
            ],
        ),
        (
            f"调出我名下的预订，再把 {booking_id} 的离店日延到 {change_date.isoformat()}。",
            ["hotel.my_bookings", "hotel.modify_booking"],
        ),
        (
            f"Pull up my reservations, then extend checkout for {booking_id} to "
            f"{change_date.isoformat()}.",
            ["hotel.my_bookings", "hotel.modify_booking"],
        ),
        (
            f"依据机场接送条款，为订单 {booking_id} 登记接机需求。",
            ["respond_with_policy", "hotel.create_service_ticket"],
        ),
        (
            f"Using the shuttle rules, lodge a pickup request for booking {booking_id}.",
            ["respond_with_policy", "hotel.create_service_ticket"],
        ),
        (
            "撤回我的本地喜好保存授权，并清空已有喜好。",
            ["memory.set_consent"],
        ),
        (
            "Revoke local preference storage and erase every saved preference.",
            ["memory.set_consent"],
        ),
    ]

    for prompt, expected_tools in workflows:
        validate_plan_completeness(
            _plan_for_intent_tools(expected_tools),
            prompt,
            "",
            INTENT_TOOL_SPECS,
        )
        for omitted in expected_tools:
            reduced = [tool for tool in expected_tools if tool != omitted]
            if not reduced:
                reduced = ["ask_user"]
            with pytest.raises(PlanCompletenessError) as captured:
                validate_plan_completeness(
                    _plan_for_intent_tools(reduced),
                    prompt,
                    "",
                    INTENT_TOOL_SPECS,
                )
            assert omitted in str(captured.value)

    contract_text = json.dumps(_PLANNING_CONTRACT, ensure_ascii=False)
    assert booking_id not in contract_text
    assert check_in.isoformat() not in contract_text
    assert change_date.isoformat() not in contract_text
    assert all(prompt not in contract_text for prompt, _ in workflows)


def test_completeness_rejects_operational_tools_without_explicit_user_intent() -> None:
    plan = _plan_for_intent_tools(["hotel.check_availability"])

    with pytest.raises(PlanCompletenessError, match="not supported"):
        validate_plan_completeness(
            plan,
            "Hello RadeonStay.",
            "",
            INTENT_TOOL_SPECS,
        )
