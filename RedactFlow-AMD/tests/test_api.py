import importlib

from fastapi.testclient import TestClient


def test_end_to_end_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REDACTFLOW_DATA_DIR", str(tmp_path))
    import app.main

    importlib.reload(app.main)
    client = TestClient(app.main.app)
    added = client.post(
        "/api/documents",
        json={"name": "brief.txt", "content": "Publish in August. Email editor@example.com."},
    )
    assert added.status_code == 200

    planned = client.post("/api/plans", json={"task": "Prepare an August public release"})
    assert planned.status_code == 200
    plan_id = planned.json()["id"]

    blocked = client.post("/api/execute", json={"plan_id": plan_id, "approved_tools": []})
    assert blocked.json()["status"] == "blocked"

    completed = client.post(
        "/api/execute",
        json={"plan_id": plan_id, "approved_tools": ["redact_documents", "write_audit_memory"]},
    )
    assert completed.json()["status"] == "completed"
    assert "[EMAIL]" in completed.json()["redacted_documents"]["brief.txt"]

