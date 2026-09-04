"""Deterministic, fail-closed preflight for versioned scenarios."""

from __future__ import annotations

from typing import Any, Mapping

from .contracts import ScenarioInput, ValidationError


class ScenarioValidationError(ValidationError):
    def __init__(self, message: str, trace: dict[str, Any]) -> None:
        super().__init__(message)
        self.trace = trace


class ScenarioValidationAgent:
    version = "scenario-validation-0.4"
    _SCENARIO_CLASSIFICATIONS = {"demonstration", "site-measured", "literature-default"}
    _SOURCE_CLASSIFICATIONS = {
        "demonstration", "demonstration-range", "site-measured",
        "literature-default", "literature-range",
    }

    def validate(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        result: dict[str, Any] = {
            "validation_version": self.version,
            "valid": False,
            "trace": trace,
            "missing_site_data": [
                "site-specific hydraulic velocity and dispersion",
                "site-specific Kd and competing-ion chemistry",
                "mineralogy, porosity, and bulk density measurements",
            ],
        }

        def fail(check: str, message: str) -> None:
            trace.append({"check": check, "status": "failed", "message": message})
            raise ScenarioValidationError(message, result)

        if entry.get("schema_version") != "nuclidepath-scenario-1.0" or not str(entry.get("library_version", "")).strip():
            fail("library_metadata", "unsupported or missing scenario-library metadata")
        if entry.get("scenario_classification") not in self._SCENARIO_CLASSIFICATIONS:
            fail("library_metadata", "unsupported scenario classification")
        behavior = entry.get("expected_qualitative_behavior")
        if not isinstance(behavior, list) or not behavior or any(
            not isinstance(item, str) or not item.strip() for item in behavior
        ):
            fail("library_metadata", "expected_qualitative_behavior must be a non-empty list of non-empty strings")
        trace.append({"check": "library_metadata", "status": "passed"})

        transport = entry.get("transport")
        if not isinstance(transport, Mapping):
            fail("transport_contract", "transport must be an object")
        try:
            scenario = ScenarioInput.from_dict(transport)
        except (ValidationError, TypeError) as exc:
            fail("transport_contract", str(exc))
        trace.append({"check": "transport_contract", "status": "passed"})
        assert isinstance(transport, Mapping)

        sources = entry.get("parameter_sources")
        if not isinstance(sources, Mapping) or not sources:
            fail("parameter_provenance", "parameter_sources must be a non-empty object")
        assert isinstance(sources, Mapping)
        for name, source in sources.items():
            if not isinstance(source, Mapping) or not str(source.get("classification", "")).strip() or not str(source.get("source", "")).strip():
                fail("parameter_provenance", f"incomplete provenance for {name}")
            if source["classification"] not in self._SOURCE_CLASSIFICATIONS:
                fail("parameter_provenance", f"unsupported provenance classification for {name}")
        transport_names = set(transport.keys()) - {"scenario_id"}
        covered_names = set(sources.keys())
        if "all_other_transport_parameters" not in covered_names and not transport_names <= covered_names:
            fail("parameter_provenance", "every transport parameter requires provenance")
        uncertainty = entry.get("uncertainty_ranges", {})
        if isinstance(uncertainty, Mapping):
            for name, value in uncertainty.items():
                if not isinstance(value, Mapping) or value.get("classification") not in self._SOURCE_CLASSIFICATIONS or not str(value.get("source", "")).strip():
                    fail("parameter_provenance", f"invalid uncertainty-range provenance for {name}")
        trace.append({"check": "parameter_provenance", "status": "passed"})

        params = scenario.to_transport_parameters()
        duration = max(scenario.evaluation_times_s)
        seconds_per_year = 365.25 * 86400.0
        trace.append({
            "check": "duration_context", "status": "passed",
            "implied_travel_time_s": scenario.distance_m * params.retardation_factor / params.groundwater_velocity_m_s,
            "simulation_duration_s": duration,
            "half_lives_simulated": duration / (scenario.half_life_years * seconds_per_year),
            "interpretation": "context only; not a pass/fail decision criterion",
        })

        if entry.get("source_term_mode", "maintained_boundary") != "maintained_boundary":
            fail("model_compatibility", "transport-prototype-0.3 supports maintained_boundary only")
        trace.append({"check": "model_compatibility", "status": "passed"})
        result["valid"] = True
        return result
