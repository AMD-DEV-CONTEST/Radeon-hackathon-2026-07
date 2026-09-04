"""Deterministic publication-schema gate for generated screening reports."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

_SCALAR = object()
_SCALAR_LIST = object()

# Fields that are physically numeric must be finite real numbers (not strings,
# booleans, NaN or infinity). Review finding: the gate previously accepted
# arbitrary scalars including strings, NaN and inf.
_NUMERIC_FIELDS = {
    "initial_concentration_bq_m3", "distance_m", "distribution_coefficient_m3_kg",
    "bulk_density_kg_m3", "porosity", "groundwater_velocity_m_s", "dispersion_m2_s",
    "potassium_mg_l", "competition_coefficient_l_mg", "half_life_years",
    "effective_kd_m3_kg", "retardation_factor", "travel_time_s",
    "sampled_max_concentration_bq_m3", "sampled_max_time_s", "time_s",
    "concentration_bq_m3", "steady_state_fraction", "decay_factor", "cells",
    "p05", "p50", "p95", "evaluation_times_s",
}

import math


def _invalid_scalar(value: Any, path: str) -> bool:
    """True when a scalar slot holds a non-finite or wrongly-typed value."""
    if path.rstrip("0123456789[]._").endswith("evaluation_times_s") or path.endswith("evaluation_times_s"):
        return False  # list handled by _SCALAR_LIST
    field = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if field in _NUMERIC_FIELDS:
        return (isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value)))
    return isinstance(value, (Mapping, list))


class ReportSafetyError(ValueError):
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        super().__init__("report safety gate failed: " + "; ".join(result["findings"]))


class ReportSafetyGate:
    version = "report-safety-0.5"
    _SCENARIO_FIELDS = {
        name: _SCALAR for name in (
            "scenario_id", "initial_concentration_bq_m3", "distance_m",
            "evaluation_times_s", "distribution_coefficient_m3_kg",
            "bulk_density_kg_m3", "porosity", "groundwater_velocity_m_s",
            "dispersion_m2_s", "potassium_mg_l", "competition_coefficient_l_mg",
            "half_life_years",
        )
    }
    _SCENARIO_FIELDS["evaluation_times_s"] = _SCALAR_LIST
    _QUANTILES = {"p05": _SCALAR, "p50": _SCALAR, "p95": _SCALAR}
    _SCHEMA: dict[str, Any] = {
        "report_version": _SCALAR,
        "execution": {"mode": _SCALAR, "planner": _SCALAR, "physics_source": _SCALAR, "llm_required": _SCALAR},
        "scenario": _SCENARIO_FIELDS,
        "comparison": {"potassium_levels_mg_l": _SCALAR_LIST, "interpretation": _SCALAR},
        "runs": [{
            "label": _SCALAR, "potassium_mg_l": _SCALAR, "effective_kd_m3_kg": _SCALAR,
            "retardation_factor": _SCALAR, "travel_time_s": _SCALAR,
            "sampled_max_concentration_bq_m3": _SCALAR, "sampled_max_time_s": _SCALAR,
            "points": [{
                "time_s": _SCALAR, "concentration_bq_m3": _SCALAR, "effective_kd_m3_kg": _SCALAR,
                "retardation_factor": _SCALAR, "travel_time_s": _SCALAR, "steady_state_fraction": _SCALAR,
                "decay_factor": _SCALAR,
            }],
            "deterministic_tool_plan": _SCALAR_LIST, "deterministic_agents_called": _SCALAR_LIST,
            "assumptions": _SCALAR_LIST, "warnings": _SCALAR_LIST, "tool": _SCALAR, "model_version": _SCALAR,
            "inputs": _SCENARIO_FIELDS,
        }],
        "phreeqc_bridge": {
            "schema": _SCALAR, "contract": _SCALAR, "status": _SCALAR,
            "input_sha256": _SCALAR, "metadata_sha256": _SCALAR,
            "output_file": _SCALAR, "cells": _SCALAR,
            "exchange_ions": _SCALAR_LIST,
            "scientific_result_qualified": _SCALAR,
            "execution_policy": _SCALAR,
        },
        "assumptions": _SCALAR_LIST, "warnings": _SCALAR_LIST,
        "scenario_library_version": _SCALAR, "scenario_schema_version": _SCALAR,
        "scenario_classification": _SCALAR,
        "parameter_sources": {"*": {"classification": _SCALAR, "source": _SCALAR}},
        "expected_qualitative_behavior": _SCALAR_LIST,
        "scenario_validation": {
            "validation_version": _SCALAR, "valid": _SCALAR, "missing_site_data": _SCALAR_LIST,
            "trace": [{
                "check": _SCALAR, "status": _SCALAR, "message": _SCALAR, "implied_travel_time_s": _SCALAR,
                "simulation_duration_s": _SCALAR, "half_lives_simulated": _SCALAR,
                "interpretation": _SCALAR,
            }],
        },
        "virtual_receptors": {
            "screening_version": _SCALAR, "scenario_id": _SCALAR, "method": _SCALAR,
            "samples": _SCALAR, "seed": _SCALAR,
            "receptors": [{
                "receptor_id": _SCALAR, "distance_m": _SCALAR,
                "arrival_time_s": _QUANTILES,
                "sampled_max_concentration_bq_m3": _QUANTILES,
                "final_concentration_bq_m3": _QUANTILES,
            }],
            "declared_range_priority": _SCALAR_LIST, "declared_range_priority_basis": _SCALAR,
            "missing_site_characterization": _SCALAR_LIST, "limitations": _SCALAR_LIST,
        },
        "report_safety_gate": {"gate_version": _SCALAR, "passed": _SCALAR, "findings": _SCALAR_LIST},
    }
    _PROHIBITED = (
        (re.compile(r"\b(site|location)\s+(?:is|remains?)\s+(?:un)?safe\b", re.I), "safety declaration"),
        (re.compile(r"\b(?:protective action|evacuation)\s+is\s+(?:un)?warranted\b", re.I), "protective-action claim"),
        (re.compile(r"\bregulatory\s+(limit|threshold|maximum)\b", re.I), "regulatory criterion claim"),
        (re.compile(r"\bdose\s+is\s+(?:un)?acceptable\b", re.I), "dose conclusion"),
        (re.compile(r"\boperations?\s+(?:may|can|should)\s+(?:safely\s+)?(?:continue|resume|stop)\b", re.I), "operational conclusion"),
        (re.compile(r"\bpeak\s+concentration\b", re.I), "unverified peak claim; use sampled maximum"),
    )

    def check(self, report: Any) -> dict[str, Any]:
        if not isinstance(report, Mapping):
            return {
                "gate_version": self.version,
                "passed": False,
                "findings": ["report root must be an object"],
            }
        findings: list[str] = []
        unsupported = self._unsupported_fields(report, self._SCHEMA)
        if unsupported:
            findings.append("unsupported report field(s): " + ", ".join(unsupported))
        text = json.dumps(report, ensure_ascii=False, sort_keys=True)
        for pattern, finding in self._PROHIBITED:
            if pattern.search(text):
                findings.append(finding)
        if "assumptions" not in report or not report.get("assumptions"):
            findings.append("results require explicit assumptions")
        runs = report.get("runs")
        if not isinstance(runs, list) or not runs:
            findings.append("results require deterministic run provenance")
        else:
            for run in runs:
                if not isinstance(run, Mapping) or not run.get("model_version") or not run.get("tool"):
                    findings.append("results require model_version and tool provenance")
                    break
                if "peak_concentration_bq_m3" in run:
                    findings.append("peak field is prohibited without an actual peak search")
                    break
        classification = report.get("scenario_classification")
        if "scenario_library_version" in report and (
            not isinstance(classification, str)
            or classification not in {"demonstration", "site-measured", "literature-default"}
        ):
            findings.append("versioned scenario values require an explicit classification")
        return {"gate_version": self.version, "passed": not findings, "findings": findings}

    @classmethod
    def _unsupported_fields(
        cls, value: Any, schema: Any, path: str = "report"
    ) -> list[str]:
        """Return dotted paths for keys outside the recursively closed report contract."""
        if schema is _SCALAR:
            return [f"{path} (invalid report value)"] if _invalid_scalar(value, path) else []
        if schema is _SCALAR_LIST:
            if not isinstance(value, list):
                return [f"{path} (invalid report value: expected list)"]
            bad = [
                f"{path}[{index}] (invalid report value)"
                for index, item in enumerate(value)
                if _invalid_scalar(item, f"{path}[{index}]")
            ]
            return bad
        if isinstance(schema, list):
            if not isinstance(value, list):
                return [f"{path} (invalid report value: expected list)"]
            if not schema:
                return []
            return [
                finding
                for index, item in enumerate(value)
                for finding in cls._unsupported_fields(item, schema[0], f"{path}[{index}]")
            ]
        if isinstance(schema, Mapping) and not isinstance(value, Mapping):
            return [f"{path} (invalid report value: expected object)"]
        if not isinstance(schema, Mapping):
            return []
        wildcard = schema.get("*")
        unsupported = sorted(
            f"{path}.{key}" for key in value if key not in schema and wildcard is None
        )
        for key, item in value.items():
            child_schema = schema.get(key, wildcard)
            if child_schema is not None:
                unsupported.extend(cls._unsupported_fields(item, child_schema, f"{path}.{key}"))
        return unsupported

    def assert_safe(self, report: Mapping[str, Any]) -> dict[str, Any]:
        result = self.check(report)
        if not result["passed"]:
            raise ReportSafetyError(result)
        return result
