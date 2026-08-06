from fastapi.testclient import TestClient
from app.main import app
def test_compute_health_has_fallback():
    with TestClient(app) as c:
        b=c.get("/api/compute/health").json();assert "accelerator" in b and b["embedding_provider"]["available"] is True
