from pathlib import Path

from fastapi.testclient import TestClient


def test_disconnect_removes_session_temp_dir(app):
    client = TestClient(app)
    session_id = client.post("/api/sessions").json()["sessionId"]
    temp_dir = Path("/tmp/silent-vision") / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / "frame.jpg").write_bytes(b"not persisted")
    with client.websocket_connect(
        f"/ws/{session_id}", headers={"origin": "http://localhost:8000"}
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.ready"
    assert not temp_dir.exists()


def test_clip_received_event_does_not_persist_raw_temp_file(app):
    client = TestClient(app)
    session_id = client.post("/api/sessions").json()["sessionId"]
    with client.websocket_connect(
        f"/ws/{session_id}", headers={"origin": "http://localhost:8000"}
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(
            {"type": "clip.start", "profileId": "global", "language": "zh"}
        )
        assert websocket.receive_json()["type"] == "clip.started"
        websocket.send_bytes(b"not-a-real-webm")
        assert websocket.receive_json()["type"] == "clip.received"
        assert websocket.receive_json()["type"] == "error"
