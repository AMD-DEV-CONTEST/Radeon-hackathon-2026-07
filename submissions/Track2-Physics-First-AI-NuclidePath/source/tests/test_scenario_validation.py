import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.scenario_validation import ScenarioValidationAgent, ScenarioValidationError


ENTRY = json.loads((Path(__file__).parents[1] / "scenarios/library/baseline_transport_v1.json").read_text())


def test_validation_agent_returns_deterministic_trace_and_duration_context():
    first = ScenarioValidationAgent().validate(ENTRY)
    second = ScenarioValidationAgent().validate(ENTRY)

    assert first == second
    assert first["validation_version"] == "scenario-validation-0.4"
    assert first["valid"] is True
    assert [check["check"] for check in first["trace"]] == [
        "library_metadata", "transport_contract", "parameter_provenance",
        "duration_context", "model_compatibility",
    ]
    duration = next(check for check in first["trace"] if check["check"] == "duration_context")
    assert duration["implied_travel_time_s"] > 0
    assert duration["simulation_duration_s"] == 1.0e10
    assert duration["half_lives_simulated"] > 0
    assert "site-specific" in " ".join(first["missing_site_data"])


def test_validation_agent_fails_closed_without_parameter_provenance():
    invalid = json.loads(json.dumps(ENTRY))
    invalid["parameter_sources"] = {}

    with pytest.raises(ScenarioValidationError) as caught:
        ScenarioValidationAgent().validate(invalid)

    assert caught.value.trace["valid"] is False
    assert caught.value.trace["trace"][-1]["status"] == "failed"


@pytest.mark.parametrize("field,value", [
    ("scenario_classification", "authoritative"),
    ("expected_qualitative_behavior", "behaves well"),
    ("expected_qualitative_behavior", [""]),
])
def test_validation_agent_rejects_invalid_classification_or_qualitative_behavior(field, value):
    invalid = json.loads(json.dumps(ENTRY))
    invalid[field] = value
    with pytest.raises(ScenarioValidationError):
        ScenarioValidationAgent().validate(invalid)


def test_validation_agent_rejects_unknown_parameter_source_classification():
    invalid = json.loads(json.dumps(ENTRY))
    invalid["parameter_sources"]["half_life_years"]["classification"] = "verified"
    with pytest.raises(ScenarioValidationError, match="classification"):
        ScenarioValidationAgent().validate(invalid)


def test_validation_agent_rejects_unprovenanced_transport_parameter():
    invalid = json.loads(json.dumps(ENTRY))
    del invalid["parameter_sources"]["all_other_transport_parameters"]
    with pytest.raises(ScenarioValidationError, match="provenance"):
        ScenarioValidationAgent().validate(invalid)
