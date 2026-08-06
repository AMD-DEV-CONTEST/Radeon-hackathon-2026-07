from datetime import timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from backend.main import create_app
from session.manager import SessionManager, SessionReplacedError


def test_create_pending_session_returns_secure_uuid():
    manager = SessionManager(pending_ttl=timedelta(seconds=30))
    created = manager.create_pending_session()
    UUID(created.session_id)
    assert created.expires_in_seconds == 30


def test_new_active_session_takes_over_active_slot():
    manager = SessionManager(pending_ttl=timedelta(seconds=30))
    first = manager.create_pending_session()
    second = manager.create_pending_session()
    old_active = manager.activate(first.session_id)
    new_active = manager.activate(second.session_id)

    assert new_active.session_id == second.session_id
    assert manager.is_current(second.session_id)
    assert not manager.is_current(first.session_id)
    try:
        manager.ensure_current(old_active)
    except SessionReplacedError as exc:
        assert exc.code == "SESSION_REPLACED"
    else:
        raise AssertionError("old active session should be marked as replaced")


def test_disconnect_releases_active_slot():
    manager = SessionManager(pending_ttl=timedelta(seconds=30))
    first = manager.create_pending_session()
    second = manager.create_pending_session()
    manager.activate(first.session_id)
    manager.disconnect(first.session_id)
    active = manager.activate(second.session_id)
    assert active.session_id == second.session_id


def test_post_sessions_returns_session_id(settings):
    app = create_app(settings)
    client = TestClient(app)
    response = client.post("/api/sessions")
    assert response.status_code == 200
    body = response.json()
    UUID(body["sessionId"])
    assert body["expiresInSeconds"] == 30


def test_clip_lifecycle_reset_commit_and_stop():
    manager = SessionManager(pending_ttl=timedelta(seconds=30))
    created = manager.create_pending_session()
    active = manager.activate(created.session_id)

    active.reset_stream()
    generation = active.stream_generation
    active.metadata["profileId"] = "browser-profile"

    assert active.streaming is True
    assert active.accepting_frames is True

    active.commit_stream()

    assert active.streaming is True
    assert active.accepting_frames is False
    assert active.stream_generation == generation

    active.stop_stream()

    assert active.streaming is False
    assert active.accepting_frames is False
    assert active.stream_generation == generation + 1
    assert active.metadata == {}
