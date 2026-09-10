"""TEST_ONLY callback runner; formal evidence uses protocol/evidence modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from specstyle.errors import DomainError
from specstyle.evaluation.protocol import FORMAL_ARMS

ArmId = Literal[
    "A_single_pass",
    "B_random_retry",
    "C_verifier_best_of_k",
    "D_directed_no_guardrail",
    "E_full_specstyle",
]


@dataclass(frozen=True, slots=True)
class ArmBudget:
    max_generations_per_input: int

    def __post_init__(self) -> None:
        if (
            type(self.max_generations_per_input) is not int
            or isinstance(self.max_generations_per_input, bool)
            or self.max_generations_per_input < 1
        ):
            raise DomainError("invalid arm budget")


@dataclass(frozen=True, slots=True)
class InputRecord:
    input_id: str
    usable: bool  # TEST_ONLY; never accepted as a formal human label.
    generations_used: int
    terminal: str


@dataclass(frozen=True, slots=True)
class ArmResult:
    arm: ArmId
    records: tuple[InputRecord, ...]
    budget: ArmBudget

    @property
    def human_usable_yield(self) -> float:
        if not self.records:
            return 0.0
        # Full denominator: every input counts.
        usable = sum(1 for r in self.records if r.usable)
        return usable / float(len(self.records))


def assign_arm(input_id: str, arms: tuple[ArmId, ...]) -> ArmId:
    """TEST_ONLY deterministic helper; formal evaluation runs every input in all arms."""
    if type(input_id) is not str or not input_id or type(arms) is not tuple or not arms:
        raise DomainError("invalid arm assignment")
    idx = sum(ord(c) for c in input_id) % len(arms)
    return arms[idx]


def run_equal_budget_arms(
    input_ids: tuple[str, ...],
    budget: ArmBudget,
    *,
    arm_executor: object,
) -> tuple[ArmResult, ...]:
    """Execute a TEST_ONLY callback harness with one maximum generation budget.

    arm_executor(arm, input_id, budget) -> InputRecord
    """
    if type(input_ids) is not tuple or not input_ids:
        raise DomainError("empty evaluation inputs")
    if not callable(arm_executor):
        raise DomainError("invalid arm executor")
    arms: tuple[ArmId, ...] = FORMAL_ARMS  # type: ignore[assignment]
    results: list[ArmResult] = []
    for arm in arms:
        records: list[InputRecord] = []
        for input_id in input_ids:
            rec = arm_executor(arm, input_id, budget)
            if type(rec) is not InputRecord:
                raise DomainError("invalid arm record")
            if rec.generations_used > budget.max_generations_per_input:
                raise DomainError("arm exceeded budget")
            records.append(rec)
        results.append(ArmResult(arm, tuple(records), budget))
    return tuple(results)
