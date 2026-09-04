import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.knowledge import LocalKnowledgeBase
from nuclear_agent.memory import LocalMemoryStore
from nuclear_agent.workflow import (
    DeterministicWorkflowPlanner,
    EmergencyWorkflow,
    LocalWorkflowPlanner,
)


def full_case():
    return {
        "site": {
            "site_id": "demo-aquifer-001",
            "event_type": "hypothetical_subsurface_release",
            "radionuclide": "Cs-137",
            "release_pathway": "groundwater",
            "source_description": "Hypothetical maintained boundary release",
            "data_provenance": "demonstration",
            "data_classification": "public",
        },
        "transport": {
            "scenario_id": "workflow-demo",
            "initial_concentration_bq_m3": 1.0e6,
            "distance_m": 100.0,
            "evaluation_times_s": [0.0, 5.0e9, 1.0e10],
            "distribution_coefficient_m3_kg": 0.2,
            "groundwater_velocity_m_s": 1.0e-5,
            "potassium_mg_l": 20.0,
        },
        "query": "How does potassium competition affect cesium retardation?",
    }


def test_emergency_workflow_exercises_all_five_track2_capabilities(tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "cesium.md").write_text(
        "# Cesium and potassium\nPotassium competition can reduce effective cesium sorption.\n"
        "Source: https://example.org/source\n"
    )
    workflow = EmergencyWorkflow(
        planner=DeterministicWorkflowPlanner(),
        knowledge_base=LocalKnowledgeBase.from_directory(knowledge_dir),
        memory=LocalMemoryStore(tmp_path / "memory.jsonl"),
    )

    result = workflow.run(full_case(), session_id="demo-session").to_dict()

    assert result["plan"] == [
        "validate_permissions",
        "site_agent",
        "knowledge_retrieval",
        "environment_agent",
        "store_memory",
        "synthesize_report",
    ]
    assert result["site_assessment"]["screening_only"] is True
    assert result["knowledge_hits"][0]["document_id"] == "cesium"
    assert result["tool_result"]["tool"] == "simulate_transport"
    assert result["memory_turns"] == 2
    assert all(result["capabilities"].values())
    assert "operational_control" in result["denied_actions"]

    class InvalidPlanner:
        def __init__(self, plan):
            self._plan = plan

        def plan(self, case):
            return list(self._plan)

    valid_plan = DeterministicWorkflowPlanner().plan(full_case())
    for invalid in (list(reversed(valid_plan)), valid_plan + [valid_plan[-1]]):
        invalid_workflow = EmergencyWorkflow(
            planner=InvalidPlanner(invalid),
            knowledge_base=LocalKnowledgeBase.from_directory(knowledge_dir),
            memory=LocalMemoryStore(tmp_path / f"invalid-{len(invalid)}.jsonl"),
        )
        with pytest.raises(ValueError, match="exactly once in safe order"):
            invalid_workflow.run(full_case(), session_id="invalid-plan")


def test_local_workflow_planner_uses_only_json_plan_from_private_client():
    class FakeClient:
        def __init__(self):
            self.messages = None

        def chat(self, messages):
            self.messages = messages
            return (
                '["validate_permissions", "site_agent", "knowledge_retrieval", '
                '"environment_agent", "store_memory", "synthesize_report"]'
            )

    client = FakeClient()
    plan = LocalWorkflowPlanner(client).plan(full_case())

    assert plan == DeterministicWorkflowPlanner().plan(full_case())
    assert client.messages[0]["role"] == "system"
    assert "local-only" in client.messages[0]["content"]
