"""Frozen Repair Core value objects."""

from __future__ import annotations

from dataclasses import dataclass, field

from specstyle.domain.enums import RepairStopReason
from specstyle.domain.identifiers import DecisionId, Identifier, RuleId
from specstyle.errors import DomainError
from specstyle.generation.requests import GenerationParameters

_MAX_VARIATION_INDEX = 2**31 - 1


def _exact_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainError(f"invalid {name}")
    return value


def _policy_version(value: object) -> str:
    if type(value) is not str or value != "1.0":
        raise DomainError("unsupported repair policy")
    return value


def _parameters(value: object) -> GenerationParameters:
    if type(value) is not GenerationParameters:
        raise DomainError("invalid repair parameters")
    rebuilt = GenerationParameters(
        value.ip_adapter_scale, value.img2img_strength, value.controlnet_scale
    )
    if rebuilt != value:
        raise DomainError("forged repair parameters")
    return rebuilt


def _identifier(value: object, expected: type[Identifier], name: str) -> Identifier:
    if type(value) is not expected:
        raise DomainError(f"invalid {name}")
    rebuilt = expected(value.value)
    if rebuilt != value:
        raise DomainError(f"forged {name}")
    return rebuilt


@dataclass(frozen=True, slots=True)
class RepairPolicy:
    policy_version: str
    max_rounds: int
    stop_after_no_improvement: int

    def __post_init__(self) -> None:
        version = _policy_version(self.policy_version)
        max_rounds = _exact_int(self.max_rounds, "max rounds", 1, 10)
        stop_after = _exact_int(
            self.stop_after_no_improvement, "stop after no improvement", 1, max_rounds
        )
        object.__setattr__(self, "policy_version", version)
        object.__setattr__(self, "max_rounds", max_rounds)
        object.__setattr__(self, "stop_after_no_improvement", stop_after)


@dataclass(frozen=True, slots=True)
class RepairPatch:
    before_parameters: GenerationParameters
    after_parameters: GenerationParameters
    before_variation_index: int
    after_variation_index: int

    def __post_init__(self) -> None:
        before = _parameters(self.before_parameters)
        after = _parameters(self.after_parameters)
        before_variation = _exact_int(
            self.before_variation_index,
            "before variation index",
            0,
            _MAX_VARIATION_INDEX,
        )
        after_variation = _exact_int(
            self.after_variation_index, "after variation index", 0, _MAX_VARIATION_INDEX
        )
        parameter_changed = before != after
        variation_changed = before_variation != after_variation
        if parameter_changed == variation_changed:
            raise DomainError("repair patch must change exactly one state category")
        object.__setattr__(self, "before_parameters", before)
        object.__setattr__(self, "after_parameters", after)
        object.__setattr__(self, "before_variation_index", before_variation)
        object.__setattr__(self, "after_variation_index", after_variation)


@dataclass(frozen=True, slots=True)
class RepairDecision:
    decision_id: DecisionId
    policy_version: str
    trigger_rule_id: RuleId
    action_id: Identifier
    patch: RepairPatch

    def __post_init__(self) -> None:
        decision_id = _identifier(self.decision_id, DecisionId, "decision id")
        version = _policy_version(self.policy_version)
        rule_id = _identifier(self.trigger_rule_id, RuleId, "trigger rule id")
        action_id = _identifier(self.action_id, Identifier, "action id")
        if type(self.patch) is not RepairPatch:
            raise DomainError("invalid repair patch")
        patch = RepairPatch(
            self.patch.before_parameters,
            self.patch.after_parameters,
            self.patch.before_variation_index,
            self.patch.after_variation_index,
        )
        if patch != self.patch:
            raise DomainError("forged repair patch")
        object.__setattr__(self, "decision_id", decision_id)
        object.__setattr__(self, "policy_version", version)
        object.__setattr__(self, "trigger_rule_id", rule_id)
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "patch", patch)


@dataclass(frozen=True, slots=True)
class NoAction:
    decision_id: DecisionId
    blocked_rule_ids: tuple[RuleId, ...]
    blocked_action_ids: tuple[Identifier, ...]
    stop_reason: RepairStopReason = field(
        init=False, default=RepairStopReason.NO_ACTION
    )

    def __post_init__(self) -> None:
        decision_id = _identifier(self.decision_id, DecisionId, "decision id")
        if type(self.blocked_rule_ids) is not tuple or not self.blocked_rule_ids:
            raise DomainError("blocked rule ids must be a nonempty exact tuple")
        if type(self.blocked_action_ids) is not tuple:
            raise DomainError("blocked action ids must be an exact tuple")
        rules = tuple(
            _identifier(rule_id, RuleId, "blocked rule id")
            for rule_id in self.blocked_rule_ids
        )
        actions = tuple(
            _identifier(action_id, Identifier, "blocked action id")
            for action_id in self.blocked_action_ids
        )
        if len(set(rules)) != len(rules) or len(set(actions)) != len(actions):
            raise DomainError("blocked ids must be unique")
        object.__setattr__(self, "decision_id", decision_id)
        object.__setattr__(self, "blocked_rule_ids", rules)
        object.__setattr__(self, "blocked_action_ids", actions)
