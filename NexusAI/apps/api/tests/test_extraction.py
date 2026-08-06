import io
from fastapi.testclient import TestClient
from app.main import app

def test_ingest_extract_graph_pipeline():
    with TestClient(app) as client:
        world = client.post(
            "/api/worlds",
            json={"name": "Extraction Test", "world_type": "memoryweaver"},
        ).json()

        upload = client.post(
            f"/api/worlds/{world['id']}/sources/upload",
            files={
                "file": (
                    "facts.txt",
                    io.BytesIO(
                        b"Aria lives in Kochi. Aria works with Noah. "
                        b"Noah maintains the NexusAI backend."
                    ),
                    "text/plain",
                )
            },
        ).json()

        extraction = client.post(
            f"/api/worlds/{world['id']}/sources/{upload['source_id']}/extract"
        )
        assert extraction.status_code == 200
        assert extraction.json()["entities_created"] >= 3
        assert extraction.json()["relationships_created"] >= 2

        graph = client.get(f"/api/worlds/{world['id']}/graph")
        assert graph.status_code == 200
        assert len(graph.json()["nodes"]) >= 3
        assert len(graph.json()["edges"]) >= 2
