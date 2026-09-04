import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from nuclear_agent.contracts import (
    ScenarioInput,
    ValidationError,
    run_transport_contract,
)


def valid_payload(**overrides):
    payload = {
        "scenario_id": "demo-cs137-k-competition",
        "initial_concentration_bq_m3": 1.0e6,
        "distance_m": 100.0,
        "evaluation_times_s": [0.0, 1.0e9],
        "distribution_coefficient_m3_kg": 0.2,
    }
    payload.update(overrides)
    return payload


def test_scenario_parses_defaults_and_is_json_serializable():
    scenario = ScenarioInput.from_dict(valid_payload())

    assert scenario.porosity == 0.35
    assert scenario.potassium_mg_l == 0.0
    encoded = json.dumps(scenario.to_dict())
    assert "demo-cs137-k-competition" in encoded


def test_scenario_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="unknown field"):
        ScenarioInput.from_dict(valid_payload(untrusted_parameter=10))


def test_scenario_rejects_invalid_physical_values():
    with pytest.raises(ValidationError, match="porosity"):
        ScenarioInput.from_dict(valid_payload(porosity=1.5))
    for overrides, message in (
        ({"scenario_id": 42}, "scenario_id must be a string"),
        ({"distance_m": True}, "non-boolean number"),
        ({"initial_concentration_bq_m3": "1000"}, "non-boolean number"),
        ({"evaluation_times_s": {0: 1.0}}, "must be a list"),
        ({"evaluation_times_s": [0.0, False]}, "non-boolean number"),
    ):
        with pytest.raises(ValidationError, match=message):
            ScenarioInput.from_dict(valid_payload(**overrides))
    with pytest.raises(ValidationError, match="unknown field"):
        ScenarioInput.from_dict({**valid_payload(), 7: "numeric-key"})


def test_transport_contract_returns_versioned_points_and_provenance():
    result = run_transport_contract(valid_payload(potassium_mg_l=100.0))
    data = result.to_dict()

    assert data["tool"] == "simulate_transport"
    assert data["model_version"] == "transport-prototype-0.3"
    assert data["scenario_id"] == "demo-cs137-k-competition"
    assert len(data["points"]) == 2
    assert data["inputs"]["potassium_mg_l"] == 100.0
    assert "reactive Ogata-Banks analytical solution" in data["assumptions"]
