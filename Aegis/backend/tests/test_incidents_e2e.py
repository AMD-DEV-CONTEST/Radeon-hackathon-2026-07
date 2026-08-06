"""
End-to-end test: register a user, create an incident, let the (fake-LLM-backed)
investigation run synchronously, and verify the incident reaches a root cause
with persisted evidence — this is the test that proves Phases 3-11 integrate
correctly as a whole system, not just in isolation.
"""
import json

import pytest

from app.agents import graph as graph_module
from tests.fakes import FakeInferenceClient


@pytest.fixture(autouse=True)
def patch_inference_client(monkeypatch):
    """Every agent constructed inside build_incident_graph() calls
    get_inference_client() by default; monkeypatch it process-wide for this
    test module so the whole graph runs against the fake."""
    fake = FakeInferenceClient(
        scripted_responses={
            "Planning agent": json.dumps(
                {"investigation_plan": ["log_analyst"], "hypotheses_to_test": ["connection pool exhaustion"]}
            ),
            "Log Analysis agent": "Connection timeouts spiking since 14:02 UTC. Confidence 0.75.",
            "Synthesis agent": json.dumps(
                {
                    "ranked_hypotheses": [
                        {"statement": "Connection pool exhaustion", "confidence": 0.8, "supporting_evidence": ["log_analyst"]}
                    ],
                    "root_cause_summary": "Connection pool exhausted under traffic spike",
                    "root_cause_confidence": 0.8,
                }
            ),
            "Remediation Planning agent": json.dumps(
                {"action": "restart_service", "service": "checkout-service", "resource_id": "checkout-service",
                 "justification": "Restart clears the exhausted pool", "risk_level": "low"}
            ),
        }
    )
    import app.agents.base as base_module

    monkeypatch.setattr(base_module, "get_inference_client", lambda: fake)
    yield


@pytest.mark.asyncio
async def test_full_incident_investigation_reaches_root_cause(client, db_session):
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "oncall@aegis.dev", "password": "supersecret1", "full_name": "On Call", "role": "sre"},
    )
    assert register.status_code == 201

    login = await client.post("/api/v1/auth/login", json={"email": "oncall@aegis.dev", "password": "supersecret1"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={
            "title": "Checkout service 500 errors",
            "description": "Spike in 5xx responses on checkout-service starting 14:02 UTC",
            "source": "manual",
            "severity": "sev2",
            "service_hint": "checkout-service",
        },
    )
    assert create_resp.status_code == 202
    incident_id = create_resp.json()["id"]

    # FastAPI's BackgroundTasks run asynchronously after the response is sent,
    # with no guaranteed completion time observable from the test client, so
    # we drive the investigation directly through the service layer here
    # (the same code path the background task calls) for a deterministic test.
    import uuid as _uuid

    from app.services.incident_service import IncidentService

    service = IncidentService()
    incident = await service.get_incident(db_session, _uuid.UUID(incident_id))
    await service.run_investigation(db_session, incident, service_hint="checkout-service")
    await db_session.commit()

    detail_resp = await client.get(f"/api/v1/incidents/{incident_id}")
    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert body["status"] in ("root_cause_identified", "remediation_pending_approval")
    assert body["root_cause_summary"] is not None
    assert body["root_cause_confidence"] == 0.8
    assert len(body["evidence"]) == 1
    assert body["evidence"][0]["source_agent"] == "log_analyst"
