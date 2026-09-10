from dataclasses import FrozenInstanceError, fields

import pytest

from specstyle.domain.enums import RepairStopReason
from specstyle.domain.identifiers import DecisionId, Identifier, RuleId
from specstyle.errors import DomainError
from specstyle.generation.requests import GenerationParameters
from specstyle.repair.models import NoAction, RepairDecision, RepairPatch, RepairPolicy


def _parameters() -> GenerationParameters:
    return GenerationParameters(0.55, 0.45, 0.7)


def _patch() -> RepairPatch:
    return RepairPatch(_parameters(), GenerationParameters(0.65, 0.45, 0.7), 0, 0)


def test_policy_accepts_exact_supported_version_and_boundaries() -> None:
    policy = RepairPolicy("1.0", 10, 10)

    assert policy == RepairPolicy("1.0", 10, 10)


@pytest.mark.parametrize(
    ("policy_version", "max_rounds", "stop_after_no_improvement"),
    (
        ("1", 1, 1),
        ("2.0", 1, 1),
        (1.0, 1, 1),
        ("1.0", True, 1),
        ("1.0", 0, 1),
        ("1.0", 11, 1),
        ("1.0", 1, True),
        ("1.0", 1, 0),
        ("1.0", 1, 2),
    ),
)
def test_policy_rejects_non_contract_values(
    policy_version: object, max_rounds: object, stop_after_no_improvement: object
) -> None:
    with pytest.raises(DomainError):
        RepairPolicy(  # type: ignore[arg-type]
            policy_version, max_rounds, stop_after_no_improvement
        )


def test_patch_rebuilds_nested_parameters_and_allows_one_change_category() -> None:
    before = _parameters()
    patch = RepairPatch(before, GenerationParameters(0.65, 0.45, 0.7), 4, 4)
    retry = RepairPatch(before, before, 4, 5)

    assert patch.before_parameters == before
    assert patch.before_parameters is not before
    assert retry.after_variation_index == 5


@pytest.mark.parametrize(
    ("before_parameters", "after_parameters", "before_variation", "after_variation"),
    (
        (_parameters(), _parameters(), 0, 0),
        (_parameters(), GenerationParameters(0.65, 0.45, 0.7), 0, 1),
        (_parameters(), GenerationParameters(0.65, 0.45, 0.7), True, 0),
        (_parameters(), GenerationParameters(0.65, 0.45, 0.7), 0, 2**31),
        ("invalid", _parameters(), 0, 1),
    ),
)
def test_patch_rejects_noop_mixed_or_invalid_values(
    before_parameters: object,
    after_parameters: object,
    before_variation: object,
    after_variation: object,
) -> None:
    with pytest.raises(DomainError):
        RepairPatch(  # type: ignore[arg-type]
            before_parameters, after_parameters, before_variation, after_variation
        )


def test_patch_rejects_forged_nested_parameters() -> None:
    before = _parameters()
    object.__setattr__(before, "ip_adapter_scale", "forged")

    with pytest.raises(DomainError):
        RepairPatch(before, GenerationParameters(0.65, 0.45, 0.7), 0, 0)


def test_decision_rebuilds_all_nested_values() -> None:
    patch = _patch()
    decision_id = DecisionId("decision")
    rule_id = RuleId("rule")
    action_id = Identifier("action")
    decision = RepairDecision(decision_id, "1.0", rule_id, action_id, patch)

    assert decision.decision_id is not decision_id
    assert decision.trigger_rule_id is not rule_id
    assert decision.action_id is not action_id
    assert decision.patch is not patch
    assert decision.patch == patch


@pytest.mark.parametrize(
    ("decision_id", "policy_version", "rule_id", "action_id", "patch"),
    (
        (Identifier("decision"), "1.0", RuleId("rule"), Identifier("action"), _patch()),
        (DecisionId("decision"), "1", RuleId("rule"), Identifier("action"), _patch()),
        (
            DecisionId("decision"),
            "1.0",
            Identifier("rule"),
            Identifier("action"),
            _patch(),
        ),
        (DecisionId("decision"), "1.0", RuleId("rule"), RuleId("action"), _patch()),
        (DecisionId("decision"), "1.0", RuleId("rule"), Identifier("action"), "patch"),
    ),
)
def test_decision_rejects_non_exact_or_invalid_values(
    decision_id: object,
    policy_version: object,
    rule_id: object,
    action_id: object,
    patch: object,
) -> None:
    with pytest.raises(DomainError):
        RepairDecision(  # type: ignore[arg-type]
            decision_id, policy_version, rule_id, action_id, patch
        )


def test_no_action_preserves_exact_order_and_has_no_mutable_status_fields() -> None:
    no_action = NoAction(
        DecisionId("decision"),
        (RuleId("first"), RuleId("second")),
        (Identifier("second-action"), Identifier("first-action")),
    )

    assert no_action.blocked_rule_ids == (RuleId("first"), RuleId("second"))
    assert no_action.blocked_action_ids == (
        Identifier("second-action"),
        Identifier("first-action"),
    )
    assert no_action.stop_reason is RepairStopReason.NO_ACTION
    assert tuple(field.name for field in fields(NoAction)) == (
        "decision_id",
        "blocked_rule_ids",
        "blocked_action_ids",
        "stop_reason",
    )


def test_no_action_rebuilds_nested_values_and_rejects_forged_members() -> None:
    decision_id = DecisionId("decision")
    rule_id = RuleId("rule")
    action_id = Identifier("action")
    no_action = NoAction(decision_id, (rule_id,), (action_id,))

    assert no_action.decision_id is not decision_id
    assert no_action.blocked_rule_ids[0] is not rule_id
    assert no_action.blocked_action_ids[0] is not action_id

    object.__setattr__(rule_id, "value", "forged value")
    with pytest.raises(DomainError):
        NoAction(DecisionId("other"), (rule_id,), ())


@pytest.mark.parametrize(
    ("rules", "actions"),
    (
        ((), ()),
        ([RuleId("rule")], ()),
        ((Identifier("rule"),), ()),
        ((RuleId("rule"), RuleId("rule")), ()),
        ((RuleId("rule"),), [Identifier("action")]),
        ((RuleId("rule"),), (RuleId("action"),)),
        ((RuleId("rule"),), (Identifier("action"), Identifier("action"))),
    ),
)
def test_no_action_requires_exact_nonempty_unique_tuples(
    rules: object, actions: object
) -> None:
    with pytest.raises(DomainError):
        NoAction(DecisionId("decision"), rules, actions)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "field_name", "replacement"),
    (
        (RepairPolicy("1.0", 1, 1), "max_rounds", 2),
        (_patch(), "after_variation_index", 1),
        (
            RepairDecision(
                DecisionId("decision"),
                "1.0",
                RuleId("rule"),
                Identifier("action"),
                _patch(),
            ),
            "policy_version",
            "2.0",
        ),
        (
            NoAction(DecisionId("decision"), (RuleId("rule"),), ()),
            "decision_id",
            DecisionId("other"),
        ),
    ),
)
def test_repair_models_are_frozen_and_slotted(
    value: object, field_name: str, replacement: object
) -> None:
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, replacement)
    with pytest.raises((AttributeError, TypeError)):
        setattr(value, "unexpected", "value")
