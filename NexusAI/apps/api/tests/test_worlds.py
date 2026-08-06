from pathlib import Path
from fastapi.testclient import TestClient
from app.database import Base, engine
from app.main import app

client = TestClient(app)

def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def teardown_module():
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

    Path("test_nexusai.db").unlink(missing_ok=True)

def test_create_world_persists():
    response = client.post(
        "/api/worlds",
        json={"name": "Persistent CodeVerse", "world_type": "codeverse"},
    )
    assert response.status_code == 201
    created = response.json()

    response = client.get(f"/api/worlds/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Persistent CodeVerse"

def test_list_worlds():
    response = client.get("/api/worlds")
    assert response.status_code == 200
    assert len(response.json()) >= 1

def test_world_catalog():
    response = client.get("/api/world-catalog")
    assert response.status_code == 200
    assert len(response.json()) == 4
