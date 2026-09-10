"""REL-001 — exercise real fail-closed paths via exercise_fault."""

from __future__ import annotations

from specstyle.reliability.fault_injection import (
    DEFAULT_SCENARIOS,
    exercise_fault,
    run_fault_suite,
)


def test_exercise_each_fault_kind_fail_closed() -> None:
    for scenario in DEFAULT_SCENARIOS:
        result = exercise_fault(scenario.kind)
        assert result.kind == scenario.kind
        assert result.failed_closed is True, result


def test_run_fault_suite_default_injector() -> None:
    results = run_fault_suite(DEFAULT_SCENARIOS)
    assert len(results) == len(DEFAULT_SCENARIOS)
    assert all(r.failed_closed for r in results)
