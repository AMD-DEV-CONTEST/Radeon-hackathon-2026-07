import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.report_safety import ReportSafetyError, ReportSafetyGate
from nuclear_agent.reporting import build_report


PAYLOAD = {"scenario_id": "gate-demo", "initial_concentration_bq_m3": 1e6, "distance_m": 10.0,
           "evaluation_times_s": [0.0, 1e9], "distribution_coefficient_m3_kg": 0.2}


def test_safety_gate_passes_traceable_screening_report_deterministically():
    report = build_report(PAYLOAD)
    first = ReportSafetyGate().check(report)
    second = ReportSafetyGate().check(report)
    assert first == second == {"gate_version": "report-safety-0.5", "passed": True, "findings": []}


@pytest.mark.parametrize("unsafe", [
    "The site is safe.",
    "The site remains unsafe.",
    "Evacuation is warranted.",
    "Protective action is warranted.",
    "The regulatory limit is 10 Bq/m3.",
    "The regulatory maximum is 10 Bq/m3.",
    "This dose is acceptable.",
    "Operations may safely continue.",
    "The peak concentration is 20 Bq/m3.",
])
def test_safety_gate_fails_closed_on_prohibited_claims(unsafe):
    report = build_report(PAYLOAD)
    report["analyst_conclusion"] = unsafe
    with pytest.raises(ReportSafetyError) as caught:
        ReportSafetyGate().assert_safe(report)
    assert caught.value.result["passed"] is False
    assert caught.value.result["findings"]


def test_safety_gate_rejects_arbitrary_supplemental_metadata_even_when_nested():
    report = build_report(PAYLOAD)
    report.update({
        "scenario_library_version": "scenario-library-0.4",
        "scenario_schema_version": "nuclidepath-scenario-1.0",
        "scenario_classification": "demonstration",
        "parameter_sources": {
            "half_life_years": {"classification": "literature-default", "source": "DDEP"}
        },
        "expected_qualitative_behavior": ["deterministic"],
        "scenario_validation": {
            "validation_version": "scenario-validation-0.4", "valid": True,
            "trace": [{"check": "library_metadata", "status": "passed"}],
            "missing_site_data": ["hydraulic data"],
        },
        "virtual_receptors": {
            "screening_version": "virtual-receptors-0.4", "scenario_id": "gate-demo",
            "method": "seeded", "samples": 20, "seed": 1,
            "receptors": [{
                "receptor_id": "path-10m", "distance_m": 10.0,
                "arrival_time_s": {"p05": 1.0, "p50": 2.0, "p95": 3.0},
                "sampled_max_concentration_bq_m3": {"p05": 1.0, "p50": 2.0, "p95": 3.0},
                "final_concentration_bq_m3": {"p05": 1.0, "p50": 2.0, "p95": 3.0},
            }],
            "declared_range_priority": ["groundwater_velocity_m_s"],
            "declared_range_priority_basis": "range span",
            "missing_site_characterization": ["hydraulics"], "limitations": ["screening only"],
        },
    })
    cases = [
        ((), "metadata"),
        (("scenario",), "analyst_note"),
        (("parameter_sources", "half_life_years"), "confidence"),
        (("scenario_validation",), "approval"),
        (("scenario_validation", "trace", 0), "reviewer"),
        (("virtual_receptors",), "conclusion"),
        (("virtual_receptors", "receptors", 0), "site_status"),
        (("virtual_receptors", "receptors", 0, "arrival_time_s"), "p99"),
    ]
    for path, unknown_field in cases:
        unsafe = deepcopy(report)
        target = unsafe
        for part in path:
            target = target[part]
        target[unknown_field] = "unsupported"
        with pytest.raises(ReportSafetyError, match="unsupported report field"):
            ReportSafetyGate().assert_safe(unsafe)


@pytest.mark.parametrize("path", [
    ("assumptions",),
    ("warnings",),
    ("execution", "mode"),
    ("scenario", "scenario_id"),
    ("runs", 0, "assumptions"),
    ("runs", 0, "warnings"),
    ("runs", 0, "deterministic_tool_plan"),
    ("runs", 0, "deterministic_agents_called"),
    ("runs", 0, "points", 0, "time_s"),
])
def test_safety_gate_rejects_nested_objects_at_scalar_or_scalar_list_leaves(path):
    report = build_report(PAYLOAD)
    target = report
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = {"unsupported_nested_key": "bypass"}

    with pytest.raises(ReportSafetyError, match="invalid report value"):
        ReportSafetyGate().assert_safe(report)


@pytest.mark.parametrize("path,replacement", [
    (("runs",), {"arbitrary": "object"}),
    (("runs", 0, "points"), {"arbitrary": "object"}),
    (("scenario_validation", "trace"), {"arbitrary": "object"}),
    (("virtual_receptors", "receptors"), {"arbitrary": "object"}),
    (("virtual_receptors", "receptors", 0, "arrival_time_s"), [1, 2, 3]),
    (("parameter_sources",), ["not", "an", "object"]),
    (("scenario_classification",), {"unhashable": "object"}),
])
def test_safety_gate_fails_closed_on_wrong_structured_container_types(path, replacement):
    report = build_report(PAYLOAD)
    report.update({
        "scenario_library_version": "scenario-library-0.4",
        "scenario_schema_version": "nuclidepath-scenario-1.0",
        "scenario_classification": "demonstration",
        "parameter_sources": {},
        "expected_qualitative_behavior": [],
        "scenario_validation": {
            "validation_version": "scenario-validation-0.4", "valid": True,
            "trace": [], "missing_site_data": [],
        },
        "virtual_receptors": {
            "screening_version": "virtual-receptors-0.4", "scenario_id": "gate-demo",
            "method": "seeded", "samples": 20, "seed": 1, "receptors": [{
                "receptor_id": "path-10m", "distance_m": 10.0,
                "arrival_time_s": {"p05": 1.0, "p50": 2.0, "p95": 3.0},
                "sampled_max_concentration_bq_m3": {"p05": 1.0, "p50": 2.0, "p95": 3.0},
                "final_concentration_bq_m3": {"p05": 1.0, "p50": 2.0, "p95": 3.0},
            }],
            "declared_range_priority": [], "declared_range_priority_basis": "declared",
            "missing_site_characterization": [], "limitations": [],
        },
    })
    target = report
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement

    with pytest.raises(ReportSafetyError, match="invalid report value"):
        ReportSafetyGate().assert_safe(report)


@pytest.mark.parametrize("malformed", [None, [], "report", 42])
def test_safety_gate_fails_closed_on_malformed_root_container(malformed):
    result = ReportSafetyGate().check(malformed)
    assert result["passed"] is False
    assert any("root must be an object" in finding for finding in result["findings"])
    with pytest.raises(ReportSafetyError, match="root must be an object"):
        ReportSafetyGate().assert_safe(malformed)


def test_safety_gate_rejects_non_finite_and_wrong_typed_numeric_fields():
    """Review finding: arbitrary scalars (strings, NaN, inf) passed the gate."""
    report = build_report(PAYLOAD)
    # NaN in a physically numeric field
    bad = deepcopy(report)
    bad["scenario"]["porosity"] = float("nan")
    result = ReportSafetyGate().check(bad)
    assert result["passed"] is False
    assert any("porosity" in f for f in result["findings"])

    # infinity in a numeric field
    bad = deepcopy(report)
    bad["scenario"]["distance_m"] = float("inf")
    result = ReportSafetyGate().check(bad)
    assert result["passed"] is False

    # string in a numeric field
    bad = deepcopy(report)
    bad["runs"][0]["points"][0]["concentration_bq_m3"] = "1e9"
    result = ReportSafetyGate().check(bad)
    assert result["passed"] is False
    assert any("concentration_bq_m3" in f for f in result["findings"])

    # bool in a numeric field
    bad = deepcopy(report)
    bad["scenario"]["porosity"] = True
    result = ReportSafetyGate().check(bad)
    assert result["passed"] is False


def test_safety_gate_rejects_results_without_assumptions_or_provenance():
    report = build_report(PAYLOAD)
    del report["assumptions"]
    with pytest.raises(ReportSafetyError, match="assumptions"):
        ReportSafetyGate().assert_safe(report)


def test_safety_gate_accepts_process_only_phreeqc_bridge_metadata():
    report = build_report(PAYLOAD)
    report["phreeqc_bridge"] = {
        "schema": "nuclidepath-phreeqc-chemistry-1",
        "contract": "process-qualified-only",
        "status": "compiled-not-run",
        "input_sha256": "a" * 64,
        "metadata_sha256": "b" * 64,
        "output_file": "nuclidepath.sel",
        "cells": 20,
        "exchange_ions": ["Ca", "Cs", "K", "Na"],
        "scientific_result_qualified": False,
        "execution_policy": "trusted manual workflow only",
    }
    assert ReportSafetyGate().check(report) == {
        "gate_version": "report-safety-0.5",
        "passed": True,
        "findings": [],
    }
