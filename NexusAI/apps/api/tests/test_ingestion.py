import io
from fastapi.testclient import TestClient
from app.main import app

def test_txt_ingestion():
    with TestClient(app) as client:
        world = client.post(
            "/api/worlds",
            json={"name": "Ingestion Test", "world_type": "memoryweaver"},
        ).json()

        response = client.post(
            f"/api/worlds/{world['id']}/sources/upload",
            files={"file": ("memory.txt", io.BytesIO(b"Alice visited Kochi. Bob met Alice there."), "text/plain")},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "ingested"
        assert body["chunk_count"] >= 1

        chunks = client.get(
            f"/api/worlds/{world['id']}/sources/{body['source_id']}/chunks"
        )
        assert chunks.status_code == 200
        assert "Alice visited Kochi" in chunks.json()[0]["text"]

def test_reject_unsupported_file():
    with TestClient(app) as client:
        world = client.post(
            "/api/worlds",
            json={"name": "Unsupported Test", "world_type": "detective"},
        ).json()
        response = client.post(
            f"/api/worlds/{world['id']}/sources/upload",
            files={"file": ("malware.exe", b"nope", "application/octet-stream")},
        )
        assert response.status_code == 415
