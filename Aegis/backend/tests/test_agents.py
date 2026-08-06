"""Unit tests for the agent layer, using the FakeInferenceClient so no live
GPU/vLLM server is required — these tests verify the multi-agent reasoning
logic itself (planning, evidence accumulation, synthesis) is correct."""
import json

import pytest

from app.agents.log_analyst import LogAnalystAgent
from app.agents.planner import PlannerAgent
from app.agents.synthesizer import SynthesizerAgent
from tests.fakes import FakeInferenceClient


@pytest.mark.asyncio
async def test_planner_selects_investigation_plan(db_session):
    fake_client = FakeInferenceClient(
        scripted_responses={
            "Planning agent": json.dumps(
                {"investigation_plan": ["log_analyst", "metrics_analyst"], "hypotheses_to_test": ["memory leak"]}
            )
        }
    )
    agent = PlannerAgent(db_session, fake_client)
    state = {"incident_id": "i1", "title": "OOM crash", "description": "pods restarting", "evidence": []}
    update = await agent.run(state)
    assert update["investigation_plan"] == ["log_analyst", "metrics_analyst"]
    assert update["hypotheses_to_test"] == ["memory leak"]


@pytest.mark.asyncio
async def test_planner_falls_back_safely_on_malformed_llm_output(db_session):
    fake_client = FakeInferenceClient(scripted_responses={"Planning agent": "not valid json"})
    agent = PlannerAgent(db_session, fake_client)
    state = {"incident_id": "i1", "title": "X", "description": "Y", "evidence": []}
    update = await agent.run(state)
    # Fails safe to the full investigation rather than crashing the run.
    assert "log_analyst" in update["investigation_plan"]


@pytest.mark.asyncio
async def test_log_analyst_appends_evidence(db_session):
    fake_client = FakeInferenceClient(
        scripted_responses={"Log Analysis agent": "Spike in 500 errors at 14:02 UTC. Confidence 0.7."}
    )
    agent = LogAnalystAgent(db_session, fake_client)
    state = {"incident_id": "i1", "title": "X", "description": "Y", "service_hint": "checkout", "evidence": []}
    update = await agent.run(state)
    assert len(update["evidence"]) == 1
    assert update["evidence"][0]["source_agent"] == "log_analyst"
    assert update["evidence"][0]["evidence_type"] == "log"


@pytest.mark.asyncio
async def test_synthesizer_produces_ranked_hypotheses(db_session):
    fake_client = FakeInferenceClient(
        scripted_responses={
            "Synthesis agent": json.dumps(
                {
                    "ranked_hypotheses": [
                        {"statement": "DB pool exhaustion", "confidence": 0.85, "supporting_evidence": ["log_analyst"]}
                    ],
                    "root_cause_summary": "DB connection pool exhausted under load",
                    "root_cause_confidence": 0.85,
                }
            )
        }
    )
    agent = SynthesizerAgent(db_session, fake_client)
    state = {
        "incident_id": "i1",
        "title": "Checkout 500s",
        "evidence": [{"source_agent": "log_analyst", "evidence_type": "log", "summary": "timeouts spiked"}],
        "hypotheses_to_test": ["DB pool exhaustion"],
    }
    update = await agent.run(state)
    assert update["root_cause_confidence"] == 0.85
    assert len(update["ranked_hypotheses"]) == 1
    assert update["ranked_hypotheses"][0]["statement"] == "DB pool exhaustion"
