import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from tests.fakes import FakeModelClient
from xianglens.agent.graph import GraphServices, build_graph
from xianglens.config import PROJECT_ROOT, Settings
from xianglens.main import create_app
from xianglens.services import AppServices
from xianglens.storage.knowledge_store import (
    HashingEmbedder,
    InMemoryKnowledgeStore,
    load_knowledge_records,
)
from xianglens.storage.sqlite_store import SQLiteStore
from xianglens.tools.image_tools import ImageInspector


def _test_app(
    tmp_path: Path,
    *,
    public_sessions_enabled: bool = False,
    session_issue_limit_per_minute: int = 10,
    app_api_key: str = "test-key",
):
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_enabled=True,
        app_api_key=app_api_key,
        public_sessions_enabled=public_sessions_enabled,
        session_issue_limit_per_minute=session_issue_limit_per_minute,
        llm_base_url="https://radeon.example.test/v1",
        sqlite_path=tmp_path / "state.sqlite3",
        milvus_uri=tmp_path / "knowledge.db",
        upload_dir=tmp_path / "uploads",
    )
    settings.ensure_runtime_directories()
    database = SQLiteStore(settings.sqlite_path)
    database.initialize()
    records = load_knowledge_records(
        PROJECT_ROOT / "data/knowledge/cards.yaml",
        PROJECT_ROOT / "data/knowledge/sources.yaml",
    )
    knowledge = InMemoryKnowledgeStore(records, HashingEmbedder())
    inspector = ImageInspector(settings.max_upload_bytes, settings.max_image_pixels)
    model = FakeModelClient()
    graph = build_graph(
        GraphServices(
            model=model,
            knowledge=knowledge,
            database=database,
            image_inspector=inspector,
        )
    )
    services = AppServices(
        settings=settings,
        model=model,
        database=database,
        knowledge=knowledge,
        image_inspector=inspector,
        graph=graph,
    )
    return create_app(settings, services)


def test_access_sessions_use_bearer_tokens_and_isolate_visitors(tmp_path: Path) -> None:
    settings_key = "test-permanent-key-at-least-32-chars"
    app = _test_app(
        tmp_path,
        public_sessions_enabled=True,
        app_api_key=settings_key,
    )

    with TestClient(app) as client:
        first_session = client.post("/api/v1/session")
        assert first_session.status_code == 201
        assert first_session.headers["cache-control"] == "no-store"
        first = first_session.json()
        assert first["token_type"] == "Bearer"
        assert first["expires_in"] == 20 * 60
        assert first["session_id"].startswith("session_")
        first_headers = {"Authorization": f"Bearer {first['access_token']}"}

        thread_response = client.post(
            "/api/v1/threads",
            json={"user_id": first["session_id"]},
            headers=first_headers,
        )
        assert thread_response.status_code == 201
        assert thread_response.json()["user_id"] == first["session_id"]
        thread_id = thread_response.json()["id"]

        second = client.post("/api/v1/session").json()
        second_headers = {"Authorization": f"Bearer {second['access_token']}"}
        assert client.get(f"/api/v1/threads/{thread_id}", headers=second_headers).status_code == 404
        assert (
            client.get(
                f"/api/v1/memories?user_id={first['session_id']}", headers=second_headers
            ).status_code
            == 403
        )

        tampered = f"{first['access_token'][:-1]}x"
        assert (
            client.get(
                "/api/v1/system/status", headers={"Authorization": f"Bearer {tampered}"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"/api/v1/threads/{thread_id}", headers={"X-App-API-Key": settings_key}
            ).status_code
            == 200
        )


def test_api_executes_the_complete_graph(tmp_path: Path) -> None:
    headers = {"X-App-API-Key": "test-key"}
    image_path = next((PROJECT_ROOT / "data/fixtures/images").glob("*.jpg"))
    with TestClient(_test_app(tmp_path)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/system/status").status_code == 401
        preflight = client.options(
            "/api/v1/system/status",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-App-API-Key",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
        status_response = client.get("/api/v1/system/status", headers=headers)
        assert status_response.status_code == 200
        assert status_response.json()["model_endpoint"] == "https://radeon.example.test/v1"

        thread_response = client.post("/api/v1/threads", json={"user_id": "ada"}, headers=headers)
        assert thread_response.status_code == 201
        thread_id = thread_response.json()["id"]

        with image_path.open("rb") as image_handle:
            upload_response = client.post(
                f"/api/v1/threads/{thread_id}/images",
                files={"image": (image_path.name, image_handle, "image/jpeg")},
                headers=headers,
            )
        assert upload_response.status_code == 201
        image_id = upload_response.json()["id"]

        run_response = client.post(
            f"/api/v1/threads/{thread_id}/runs",
            headers=headers,
            json={
                "message": "Review this image for GitHub.",
                "platform": "GitHub",
                "audience": "international open-source collaborators",
                "intent_keywords": ["credible", "approachable"],
                "image_ids": [image_id],
                "enabled_packs": ["profile_basics", "global_professional_context"],
            },
        )
        assert run_response.status_code == 200
        body = run_response.json()
        assert body["status"] == "completed"
        assert len(body["tool_trace"]) == 9
        assert body["evidence"]
        assert body["performance_metrics"]["image_count"] == 1
        assert body["comparison"] is None

        state_response = client.get(f"/api/v1/threads/{thread_id}/state", headers=headers)
        assert state_response.status_code == 200
        assert len(state_response.json()["messages"]) == 2
        runs_response = client.get(f"/api/v1/threads/{thread_id}/runs", headers=headers)
        assert runs_response.status_code == 200
        assert runs_response.json()[0]["result"]["run_id"] == body["run_id"]
        stored_run = client.get(f"/api/v1/runs/{body['run_id']}", headers=headers)
        assert stored_run.status_code == 200

        safe_copy = client.post(
            f"/api/v1/threads/{thread_id}/images/{image_id}/safe-copy",
            headers=headers,
        )
        assert safe_copy.status_code == 200
        assert safe_copy.headers["content-type"] == "image/jpeg"
        assert len(safe_copy.headers["x-xianglens-sha256"]) == 64
        with Image.open(io.BytesIO(safe_copy.content)) as exported:
            assert exported.getexif() == {}

        stream_response = client.post(
            f"/api/v1/threads/{thread_id}/runs/stream",
            headers=headers,
            json={
                "message": "Review this image for GitHub.",
                "platform": "GitHub",
                "audience": "international open-source collaborators",
                "intent_keywords": ["credible"],
                "image_ids": [image_id],
                "enabled_packs": ["profile_basics"],
            },
        )
        assert stream_response.status_code == 200
        assert "event: run.started" in stream_response.text
        assert stream_response.text.count("event: node.completed") == 9
        assert '"plan": ["Apply the sensitive-inference policy gate."' in stream_response.text
        assert "event: run.completed" in stream_response.text

        proposal_response = client.post(
            f"/api/v1/threads/{thread_id}/memory-proposals",
            headers=headers,
            json={
                "user_id": "ada",
                "text": "Red is an intentional brand color.",
                "memory_type": "preference",
            },
        )
        assert proposal_response.status_code == 201
        consent_id = proposal_response.json()["consent_id"]
        assert client.get("/api/v1/memories?user_id=ada", headers=headers).json() == []
        consent_response = client.post(
            f"/api/v1/consents/{consent_id}",
            headers=headers,
            json={"action": "approve"},
        )
        assert consent_response.status_code == 200
        memories = client.get("/api/v1/memories?user_id=ada", headers=headers).json()
        assert [item["text"] for item in memories] == ["Red is an intentional brand color."]

        forget_response = client.delete("/api/v1/privacy/forget-me?user_id=ada", headers=headers)
        assert forget_response.status_code == 200
        assert forget_response.json()["threads_deleted"] == 1
        assert forget_response.json()["memories_deleted"] == 1
        assert client.get(f"/api/v1/threads/{thread_id}", headers=headers).status_code == 404
