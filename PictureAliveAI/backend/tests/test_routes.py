"""Test routes validation and health endpoint."""
from routes import MODE_MAP


def test_mode_map_complete():
    assert MODE_MAP == {
        "audio-guide": "audio_guide",
        "story-creator": "story_creator",
        "historical-guide": "historical_guide",
        "creative-studio": "creative_studio",
    }


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_invalid_mode(client):
    resp = client.post("/api/modes/fake-mode/analyze")
    assert resp.status_code == 422


def test_no_file(client):
    resp = client.post("/api/modes/audio-guide/analyze")
    assert resp.status_code == 422


def test_audio_no_text(client):
    resp = client.post("/api/audio/generate")
    assert resp.status_code in (400, 422)  # missing body