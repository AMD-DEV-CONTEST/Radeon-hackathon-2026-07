from dataclasses import replace

import pytest

from specstyle.domain.identifiers import AttemptId, DecisionId, Identifier, RuleId
from specstyle.errors import DomainError
from specstyle.generation.requests import GenerationParameters, GenerationRequest
from specstyle.repair.actions import (
    DECREASE_STYLE_SCALE,
    EXECUTABLE_ACTION_IDS,
    INCREASE_STRUCTURE,
    INCREASE_STYLE_SCALE,
    KNOWN_ACTION_IDS,
    REDUCE_DENOISE,
    RENDER_OUTPUT_PROFILE,
    RETRY_SAMPLING,
    build_repair_request,
    is_action_executable,
    plan_repair_action,
    repair_policy_from_request,
)
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.models import StyleSpecV1
from tests.unit.generation.test_requests import _request as _generation_request
from tests.unit.spec.test_compiler import context, raw_spec


class ExplodingEquality:
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("equality exploded")

    def __ne__(self, other: object) -> bool:
        raise RuntimeError("equality exploded")


def _repair_request(**changes: object) -> GenerationRequest:
    raw = raw_spec().model_dump(mode="python")
    raw["repair"]["policy_version"] = "1.0"
    return _generation_request(
        compiled_spec=compile_style_spec(StyleSpecV1.model_validate(raw), context()),
        **changes,
    )


def test_action_whitelists_have_exact_identifiers_in_contract_order() -> None:
    expected = (
        "INCREASE_STYLE_SCALE",
        "DECREASE_STYLE_SCALE",
        "REDUCE_DENOISE",
        "INCREASE_STRUCTURE",
        "RENDER_OUTPUT_PROFILE",
        "RETRY_SAMPLING",
    )

    assert tuple(action.value for action in KNOWN_ACTION_IDS) == expected
    assert all(type(action) is Identifier for action in KNOWN_ACTION_IDS)
    assert (
        tuple(action.value for action in EXECUTABLE_ACTION_IDS)
        == expected[:4] + expected[5:]
    )
    assert (
        INCREASE_STYLE_SCALE,
        DECREASE_STYLE_SCALE,
        REDUCE_DENOISE,
        INCREASE_STRUCTURE,
        RENDER_OUTPUT_PROFILE,
        RETRY_SAMPLING,
    ) == KNOWN_ACTION_IDS


def test_policy_is_built_from_the_request_source_spec() -> None:
    policy = repair_policy_from_request(_repair_request())

    assert policy.policy_version == "1.0"
    assert policy.max_rounds == 1
    assert policy.stop_after_no_improvement == 1


@pytest.mark.parametrize("version", ("1", "2.0"))
def test_policy_rejects_unknown_or_non_contract_source_versions(version: str) -> None:
    raw = raw_spec().model_dump(mode="python")
    raw["repair"]["policy_version"] = version
    request = _generation_request(
        compiled_spec=compile_style_spec(StyleSpecV1.model_validate(raw), context())
    )

    with pytest.raises(DomainError):
        repair_policy_from_request(request)


@pytest.mark.parametrize(
    ("action", "parameters", "variation", "expected_parameters", "expected_variation"),
    (
        (
            INCREASE_STYLE_SCALE,
            GenerationParameters(0.55, 0.45, 0.7),
            0,
            GenerationParameters(0.55 + 0.10, 0.45, 0.7),
            0,
        ),
        (
            DECREASE_STYLE_SCALE,
            GenerationParameters(0.55, 0.45, 0.7),
            0,
            GenerationParameters(0.55 - 0.10, 0.45, 0.7),
            0,
        ),
        (
            REDUCE_DENOISE,
            GenerationParameters(0.55, 0.45, 0.7),
            0,
            GenerationParameters(0.55, 0.45 - 0.10, 0.7),
            0,
        ),
        (
            INCREASE_STRUCTURE,
            GenerationParameters(0.55, 0.45, 0.7),
            0,
            GenerationParameters(0.55, 0.45, 0.7 + 0.10),
            0,
        ),
        (
            RETRY_SAMPLING,
            GenerationParameters(0.55, 0.45, 0.7),
            0,
            GenerationParameters(0.55, 0.45, 0.7),
            1,
        ),
    ),
)
def test_planned_executable_actions_have_exact_typed_patch_and_do_not_mutate_parent(
    action: Identifier,
    parameters: GenerationParameters,
    variation: int,
    expected_parameters: GenerationParameters,
    expected_variation: int,
) -> None:
    parent = _repair_request(
        parent_attempt_id=AttemptId("old"),
        execution_parameters=parameters,
        variation_index=variation,
    )
    before = (parent.execution_parameters, parent.variation_index, parent.request_hash)

    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), action
    )
    repeated = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), action
    )

    assert decision.patch.before_parameters == parameters
    assert decision.patch.after_parameters == expected_parameters
    assert decision.patch.before_variation_index == variation
    assert decision.patch.after_variation_index == expected_variation
    assert repeated == decision
    assert (
        parent.execution_parameters,
        parent.variation_index,
        parent.request_hash,
    ) == before


@pytest.mark.parametrize(
    ("action", "parameters", "variation"),
    (
        (INCREASE_STYLE_SCALE, GenerationParameters(1.0, 0.45, 0.7), 0),
        (DECREASE_STYLE_SCALE, GenerationParameters(0.0, 0.45, 0.7), 0),
        (REDUCE_DENOISE, GenerationParameters(0.55, 0.0, 0.7), 0),
        (INCREASE_STRUCTURE, GenerationParameters(0.55, 0.45, 1.0), 0),
        (RETRY_SAMPLING, GenerationParameters(0.55, 0.45, 0.7), 2**31 - 1),
    ),
)
def test_noop_or_upper_bound_actions_are_not_executable_or_plannable(
    action: Identifier, parameters: GenerationParameters, variation: int
) -> None:
    request = _repair_request(
        parent_attempt_id=AttemptId("old"),
        execution_parameters=parameters,
        variation_index=variation,
    )

    assert is_action_executable(request, action) is False
    with pytest.raises(DomainError):
        plan_repair_action(request, DecisionId("decision"), RuleId("rule"), action)


def test_render_is_recognized_but_unavailable_and_unknown_actions_fail_closed() -> None:
    request = _repair_request()

    assert is_action_executable(request, RENDER_OUTPUT_PROFILE) is False
    with pytest.raises(DomainError):
        plan_repair_action(
            request, DecisionId("decision"), RuleId("rule"), RENDER_OUTPUT_PROFILE
        )
    with pytest.raises(DomainError):
        is_action_executable(request, Identifier("UNKNOWN"))


def test_action_functions_reject_forged_request_action_and_ids() -> None:
    request = _repair_request()
    object.__setattr__(request, "variation_index", "forged")

    with pytest.raises(DomainError):
        repair_policy_from_request(request)
    with pytest.raises(DomainError):
        is_action_executable(request, INCREASE_STYLE_SCALE)
    with pytest.raises(DomainError):
        plan_repair_action(
            request, Identifier("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
        )


@pytest.mark.parametrize("action", EXECUTABLE_ACTION_IDS)
def test_build_child_preserves_frozen_materials_and_repairs_lineage(
    action: Identifier,
) -> None:
    parent = _repair_request()
    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), action
    )

    child = build_repair_request(parent, decision, AttemptId("child"))

    assert child.attempt_id == AttemptId("child")
    assert child.parent_attempt_id == parent.attempt_id
    assert child.execution_parameters == decision.patch.after_parameters
    assert child.variation_index == decision.patch.after_variation_index
    assert (
        child.job_id,
        child.compiled_spec,
        child.generation_profile,
        child.output_profile,
        child.source,
        child.style_references,
        child.prompt,
        child.control_input,
        child.environment_hash,
    ) == (
        parent.job_id,
        parent.compiled_spec,
        parent.generation_profile,
        parent.output_profile,
        parent.source,
        parent.style_references,
        parent.prompt,
        parent.control_input,
        parent.environment_hash,
    )
    assert child.generation_fingerprint != parent.generation_fingerprint
    if action is RETRY_SAMPLING:
        assert child.seed != parent.seed
    else:
        assert child.seed == parent.seed


def test_build_child_rejects_tampered_decision_parent_and_next_attempt() -> None:
    parent = _repair_request()
    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
    )

    object.__setattr__(decision.patch, "after_variation_index", 1)
    with pytest.raises(DomainError):
        build_repair_request(parent, decision, AttemptId("child"))

    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
    )
    object.__setattr__(decision, "action_id", Identifier("UNKNOWN"))
    with pytest.raises(DomainError):
        build_repair_request(parent, decision, AttemptId("child"))

    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
    )
    object.__setattr__(decision, "policy_version", "2.0")
    with pytest.raises(DomainError):
        build_repair_request(parent, decision, AttemptId("child"))

    parent = _repair_request()
    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
    )
    object.__setattr__(parent, "execution_parameters", "forged")
    with pytest.raises(DomainError):
        build_repair_request(parent, decision, AttemptId("child"))

    parent = _repair_request()
    parent = replace(parent, attempt_id=AttemptId("parent"))
    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
    )
    with pytest.raises(DomainError):
        build_repair_request(parent, decision, parent.attempt_id)
    with pytest.raises(DomainError):
        build_repair_request(parent, decision, Identifier("not-attempt"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    ("policy_version", "max_rounds", "stop_after_no_improvement"),
)
def test_build_child_converts_forged_repair_policy_material_to_domain_error(
    field_name: str,
) -> None:
    parent = _repair_request()
    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
    )
    object.__setattr__(parent.compiled_spec.source_spec.repair, field_name, object())

    with pytest.raises(DomainError, match="^invalid generation request$") as error:
        build_repair_request(parent, decision, AttemptId("child"))

    assert error.value.__cause__ is not None


def test_build_child_converts_forged_control_image_to_domain_error() -> None:
    parent = _repair_request()
    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
    )
    object.__setattr__(parent.control_input, "image", object())

    with pytest.raises(DomainError, match="^invalid generation request$") as error:
        build_repair_request(parent, decision, AttemptId("child"))

    assert error.value.__cause__ is not None


@pytest.mark.parametrize(
    "field_name", ("seed", "request_hash", "generation_fingerprint")
)
def test_build_child_converts_forged_init_only_equality_to_domain_error(
    field_name: str,
) -> None:
    parent = _repair_request()
    decision = plan_repair_action(
        parent, DecisionId("decision"), RuleId("rule"), INCREASE_STYLE_SCALE
    )
    object.__setattr__(parent, field_name, ExplodingEquality())

    with pytest.raises(DomainError, match="^invalid generation request$") as error:
        build_repair_request(parent, decision, AttemptId("child"))

    assert type(error.value.__cause__) is RuntimeError
