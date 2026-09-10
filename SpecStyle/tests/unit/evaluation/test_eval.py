"""EVAL-002/003 runners."""

from __future__ import annotations

from specstyle.evaluation.arms import (
    ArmBudget,
    InputRecord,
    run_equal_budget_arms,
)
from specstyle.evaluation.stats import compare_arms
from specstyle.evaluation.protocol import FORMAL_ARMS


def test_five_arms_full_denominator() -> None:
    budget = ArmBudget(3)

    def executor(arm, input_id, budget):
        # A always usable with 1 gen; others vary but never exceed budget
        usable = arm == "E_full_specstyle" or input_id.endswith("0")
        return InputRecord(input_id, usable, 1, "COMPLETED" if usable else "REJECTED")

    results = run_equal_budget_arms(
        ("in0", "in1", "in2"), budget, arm_executor=executor
    )
    assert len(results) == 5
    assert tuple(result.arm for result in results) == FORMAL_ARMS
    for arm in results:
        assert len(arm.records) == 3
        assert 0.0 <= arm.human_usable_yield <= 1.0
    stats = compare_arms(results)
    assert len(stats) == 5
    assert stats[0].n_inputs == 3
