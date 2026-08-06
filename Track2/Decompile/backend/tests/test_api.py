from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_is_local():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["inference"] == "local"

def test_project_creation():
    response = client.post("/api/projects", json={"url": "https://youtu.be/demo123"})
    assert response.status_code == 202
    assert response.json()["source_url"].endswith("demo123")
