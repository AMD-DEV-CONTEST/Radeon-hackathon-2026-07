from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.cases import create_app
from app.rag.corpus import LegalCorpusStore, load_manifest
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.index import LegalVectorIndex


def _experience_app(tmp_path):
    documents, chunks = load_manifest("data/laws/source_manifest.json")
    corpus_path = tmp_path / "legal.sqlite3"
    LegalCorpusStore(corpus_path).replace(documents, chunks)
    qdrant_path = tmp_path / "qdrant"
    index = LegalVectorIndex(
        qdrant_path,
        HashEmbeddingProvider(dimension=384),
    )
    index.rebuild(chunks)
    index.close()
    return create_app(
        case_root=tmp_path / "cases",
        checkpoint_path=tmp_path / "checkpoints.sqlite3",
        legal_corpus_path=corpus_path,
        qdrant_path=qdrant_path,
    )


def test_experience_page_runs_real_business_agents(tmp_path):
    client = TestClient(_experience_app(tmp_path))
    page = client.get("/experience")
    assert page.status_code == 200
    assert "运行三个 Agent" in page.text
    assert "不使用公网模型 API" in page.text

    scenarios = client.get("/experience/scenarios")
    assert scenarios.status_code == 200
    assert {item["scenario_id"] for item in scenarios.json()} == {
        "demo_a",
        "demo_b",
        "demo_c",
    }

    response = client.post("/experience/run/demo_a")
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_node"] == "human_approval"
    assert payload["verifier_results"]["passed"] is True
    assert payload["intake_assessment"]["route_hint"] == "evidence_ready"
    assert payload["vehicle_nature_result"]["classification"] == "non_motor_vehicle"
    assert (
        payload["liability_result"]["insurance_payment_estimate"]["status"]
        == "insufficient_data"
    )

    findings = {
        (item["party"], item["category"]): item
        for item in payload["liability_result"]["violation_matrix"]
    }
    assert findings[("two_wheeler", "speed")]["status"] == "unknown"
    assert findings[("motor_vehicle", "braking_avoidance")]["status"] == "refuted"
    assert findings[("two_wheeler", "right_of_way")]["status"] == "confirmed"


def test_experience_unknown_scenario_fails_closed(tmp_path):
    client = TestClient(_experience_app(tmp_path))
    response = client.post("/experience/run/not-a-scenario")
    assert response.status_code == 404
