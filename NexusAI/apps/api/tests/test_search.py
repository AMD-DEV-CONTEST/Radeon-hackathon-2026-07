import io
from fastapi.testclient import TestClient
from app.main import app

def test_world_search():
    with TestClient(app) as client:
        world = client.post(
            "/api/worlds",
            json={"name": "Retrieval Test", "world_type": "memoryweaver"},
        ).json()

        client.post(
            f"/api/worlds/{world['id']}/sources/upload",
            files={
                "file": (
                    "facts.txt",
                    io.BytesIO(
                        b"Aria lives in Kochi. Noah maintains the NexusAI backend. "
                        b"The Nexus Research Lab is located in Bengaluru."
                    ),
                    "text/plain",
                )
            },
        )

        response = client.get(
            f"/api/worlds/{world['id']}/search",
            params={"q": "NexusAI backend", "top_k": 3},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["results"]
        assert "NexusAI backend" in body["results"][0]["text"]
