from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openalpha_sentinel.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "runtime"
    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "openalpha.db",
        offline=False,
        allowed_domains=("api.github.com", "github.com"),
        llm_backend="heuristic",
    )


@pytest.fixture
def api_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, FastAPI]]:
    # Importing the API module constructs its default ASGI app, so isolate that
    # module-level instance as well as the app under test inside tmp_path.
    monkeypatch.setenv(
        "OPENALPHA_DATA_DIR", str(settings.data_dir.parent / "module-default")
    )
    monkeypatch.setenv("OPENALPHA_LLM_BACKEND", "heuristic")
    from openalpha_sentinel.api import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        yield client, app


def _json(response: Any) -> Any:
    assert response.status_code < 400, response.text
    return response.json()


def test_health_is_local_and_reports_configured_backend(
    api_client: tuple[TestClient, FastAPI],
):
    client, _ = api_client

    health = _json(client.get("/api/health"))
    dashboard = _json(client.get("/api/dashboard"))

    assert health == {
        "status": "ok",
        "version": "0.1.0",
        "llm_backend": "heuristic-local",
        "offline": False,
    }
    assert dashboard == {
        "strategies": 0,
        "sources": 0,
        "revisions": 0,
        "active_watch_rules": 0,
        "jobs_last_24h": 0,
        "notifications": 0,
        "offline": False,
        "llm_backend": "heuristic-local",
    }


def test_demo_seed_is_idempotent_and_powers_cards_dashboard_and_chat(
    api_client: tuple[TestClient, FastAPI],
):
    client, _ = api_client

    first = _json(client.post("/api/demo/seed"))
    second = _json(client.post("/api/demo/seed"))

    assert first["state"] == "COMPLETED"
    assert first["processed"] == 3
    assert first["created_cards"] == 3
    assert first["skipped_revisions"] == 0
    assert second["state"] == "COMPLETED"
    assert second["processed"] == 3
    assert second["created_cards"] == 0
    assert second["skipped_revisions"] == 3

    dashboard = _json(client.get("/api/dashboard"))
    assert dashboard["strategies"] == 3
    assert dashboard["sources"] == 3
    assert dashboard["revisions"] == 3
    assert dashboard["jobs_last_24h"] == 2
    assert dashboard["notifications"] == 3

    cards = _json(client.get("/api/cards?limit=10&offset=0"))
    assert len(cards) == 3
    assert {card["title"] for card in cards} == {
        "Crypto Volatility-Scaled Trend Following",
        "Cointegrated ETF Pairs Research",
        "Daily Equity Mean Reversion",
    }
    assert all(card["immutable_url"] for card in cards)
    assert all(card["revision_key"] for card in cards)

    detail = _json(client.get(f"/api/cards/{cards[0]['id']}"))
    assert detail["id"] == cards[0]["id"]
    assert detail["title"] == cards[0]["title"]
    assert detail["evidence"]
    assert all(item["field_name"] for item in detail["evidence"])
    assert all(item["chunk_id"] for item in detail["evidence"])
    assert all(item["source_url"] for item in detail["evidence"])

    missing = client.get("/api/cards/card-does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Strategy card not found"

    answer = _json(
        client.post(
            "/api/chat",
            json={"question": "有哪些策略？", "session_id": "api-list-session"},
        )
    )
    assert answer["backend"] == "deterministic-tool"
    assert "当前收录的策略" in answer["answer"]
    assert len(answer["citations"]) == 3
    assert {citation["label"] for citation in answer["citations"]} == {
        "S1",
        "S2",
        "S3",
    }
    assert {citation["url"] for citation in answer["citations"]} == {
        card["immutable_url"] for card in cards
    }
    assert all(step["status"] == "completed" for step in answer["steps"])

    assert len(_json(client.get("/api/sources"))) == 3
    assert len(_json(client.get("/api/jobs"))) == 2
    assert len(_json(client.get("/api/notifications"))) == 3


def test_web_card_detail_fetches_evidence_from_detail_endpoint(
    api_client: tuple[TestClient, FastAPI],
):
    client, _ = api_client
    _json(client.post("/api/demo/seed"))

    card = _json(client.get("/api/cards?limit=1"))[0]
    assert "evidence" not in card

    detail = _json(client.get(f"/api/cards/{card['id']}"))
    assert detail["evidence"]

    app_javascript = client.get("/app.js")
    assert app_javascript.status_code == 200
    assert "application/javascript" in app_javascript.headers["content-type"]
    assert 'request(`/cards/${encodeURIComponent(cardId)}`)' in app_javascript.text
    assert "openCardDetail(element.dataset.cardId)" in app_javascript.text


def test_watch_rule_create_list_run_and_validation_are_offline(
    api_client: tuple[TestClient, FastAPI], monkeypatch: pytest.MonkeyPatch
):
    client, app = api_client
    service = app.state.service

    created = _json(
        client.post(
            "/api/watch-rules",
            json={
                "name": "Mean reversion repositories",
                "kind": "github",
                "config": {"query": "mean reversion", "limit": 3},
                "interval_minutes": 15,
            },
        )
    )
    assert created["enabled"] is True
    assert created["kind"] == "github"
    assert created["config"] == {"limit": 3, "query": "mean reversion"}
    assert created["last_run_at"] is None

    listed = _json(client.get("/api/watch-rules"))
    assert [rule["id"] for rule in listed] == [created["id"]]

    # Preserve the full API -> Service -> Pipeline -> scheduler path while
    # replacing only the external GitHub fetch with deterministic local data.
    monkeypatch.setattr(
        service,
        "discover_github",
        lambda query, limit: service.seed_demo(),
    )
    run = _json(client.post(f"/api/watch-rules/{created['id']}/run"))
    assert run["state"] == "COMPLETED"
    assert run["created_cards"] == 3

    updated = _json(client.get("/api/watch-rules"))[0]
    assert updated["last_run_at"] is not None
    assert updated["next_run_at"] > updated["last_run_at"]

    unknown = client.post("/api/watch-rules/watch-missing/run")
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Watch rule not found"

    unsupported = client.post(
        "/api/watch-rules",
        json={
            "name": "Unsupported",
            "kind": "web",
            "config": {},
            "interval_minutes": 15,
        },
    )
    assert unsupported.status_code == 400
    assert "kind must be github or rss" in unsupported.json()["detail"]

    invalid_interval = client.post(
        "/api/watch-rules",
        json={
            "name": "Too frequent",
            "kind": "github",
            "config": {"query": "alpha"},
            "interval_minutes": 1,
        },
    )
    assert invalid_interval.status_code == 422


def test_permission_endpoints_persist_domains_and_block_network_when_offline(
    api_client: tuple[TestClient, FastAPI],
):
    client, _ = api_client

    initial = _json(client.get("/api/permissions"))
    assert initial == {
        "offline": False,
        "allowed_domains": ["api.github.com", "github.com"],
    }

    granted = _json(
        client.post(
            "/api/permissions/domains", json={"domain": ".Feeds.Example.COM"}
        )
    )
    assert granted["allowed_domains"] == [
        "api.github.com",
        "feeds.example.com",
        "github.com",
    ]

    offline = _json(
        client.post("/api/permissions/offline", json={"enabled": True})
    )
    assert offline["offline"] is True
    assert _json(client.get("/api/health"))["offline"] is True

    blocked = client.post(
        "/api/discover/github", json={"query": "mean reversion", "limit": 1}
    )
    assert blocked.status_code == 403
    assert "offline mode" in blocked.json()["detail"]

    online = _json(
        client.post("/api/permissions/offline", json={"enabled": False})
    )
    assert online["offline"] is False
    assert "feeds.example.com" in online["allowed_domains"]


def test_memory_endpoints_show_and_delete_preferences_and_sessions(
    api_client: tuple[TestClient, FastAPI],
):
    client, app = api_client

    remembered = _json(
        client.post(
            "/api/chat",
            json={
                "question": "记住以后只看 MIT 许可证策略",
                "session_id": "api-memory-session",
            },
        )
    )
    assert remembered["backend"] == "deterministic-tool"
    assert "保存在本地" in remembered["answer"]

    memory = _json(client.get("/api/memory"))
    assert memory["preferences"]["research_filter"] == {
        "instruction": "记住以后只看 MIT 许可证策略",
        "license": "MIT",
    }
    assert len(
        app.state.service.database.recent_messages(
            "api-memory-session", limit=10
        )
    ) == 2

    deleted_preference = _json(
        client.delete("/api/memory/preferences/research_filter")
    )
    assert deleted_preference == {"deleted": True}
    after_preference_delete = _json(client.get("/api/memory"))
    assert after_preference_delete["preferences"] == {}
    assert after_preference_delete["conversations"][0]["session_id"] == "api-memory-session"
    assert _json(client.delete("/api/memory/preferences/research_filter")) == {
        "deleted": False
    }

    deleted_session = _json(
        client.delete("/api/memory/sessions/api-memory-session")
    )
    assert deleted_session == {"deleted": True}
    assert (
        app.state.service.database.recent_messages(
            "api-memory-session", limit=10
        )
        == []
    )
    assert _json(client.get("/api/memory"))["conversations"] == []
    assert _json(client.delete("/api/memory/sessions/api-memory-session")) == {
        "deleted": False
    }

    audit = _json(client.get("/api/audit"))
    assert {event["event_type"] for event in audit}.issuperset(
        {"tool_call", "preference_deleted", "conversation_deleted"}
    )
