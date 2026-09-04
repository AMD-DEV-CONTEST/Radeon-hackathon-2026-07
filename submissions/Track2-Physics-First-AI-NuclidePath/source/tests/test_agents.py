import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from nuclear_agent.agents import DeterministicPlanner, Orchestrator


def payload():
    return {
        "scenario_id": "orchestrator-demo",
        "initial_concentration_bq_m3": 1.0e6,
        "distance_m": 100.0,
        "evaluation_times_s": [0.0, 5.0e9],
        "distribution_coefficient_m3_kg": 0.2,
        "groundwater_velocity_m_s": 1.0e-5,
        "potassium_mg_l": 20.0,
    }


def test_orchestrator_delegates_environment_calculation_and_returns_trace():
    run = Orchestrator(planner=DeterministicPlanner()).run(payload())
    data = run.to_dict()

    assert data["scenario_id"] == "orchestrator-demo"
    assert data["agents_called"] == ["environment_agent"]
    assert data["plan"] == ["validate_input", "environment_agent", "synthesize_report"]
    assert data["tool_result"]["tool"] == "simulate_transport"
    assert data["tool_result"]["points"][1]["concentration_bq_m3"] > 0
    assert data["warnings"]


def test_orchestrator_rejects_planner_steps_that_are_not_allowed():
    class UnsafePlanner:
        def plan(self, payload):
            return ["execute_control_action"]

    with pytest.raises(ValueError, match="unsupported plan step"):
        Orchestrator(planner=UnsafePlanner()).run(payload())
