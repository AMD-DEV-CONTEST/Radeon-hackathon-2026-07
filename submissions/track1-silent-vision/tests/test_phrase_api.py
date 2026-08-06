from fastapi.testclient import TestClient

from command.catalog import PhraseCatalog, catalog_records


def test_get_phrases_returns_the_active_catalog_without_creating_a_session(
    app, monkeypatch
):
    def fail_if_session_is_created():
        raise AssertionError("phrase lookup must not create a session")

    monkeypatch.setattr(
        app.state.session_manager,
        "create_pending_session",
        fail_if_session_is_created,
    )

    response = TestClient(app).get("/api/phrases")

    assert response.status_code == 200
    assert response.json() == {
        "phrases": catalog_records(app.state.phrase_catalog)
    }


def test_get_phrases_reads_the_current_app_catalog(app):
    active_catalog = PhraseCatalog.from_records(
        [
            {
                "phraseId": "en_only",
                "text": "Have you eaten?",
                "language": "en",
                "intent": "CHAT_OTHER",
                "enabled": True,
            }
        ]
    )
    app.state.phrase_catalog = active_catalog

    response = TestClient(app).get("/api/phrases")

    assert response.status_code == 200
    assert response.json() == {"phrases": catalog_records(active_catalog)}
