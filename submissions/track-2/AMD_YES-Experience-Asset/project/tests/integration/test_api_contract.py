from __future__ import annotations

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.domain.enums import TerminalState


def test_health_reports_local_only_and_unverified_gpu(tmp_path) -> None:
    app = create_app(
        database_path=tmp_path / "asset.sqlite3",
        model_endpoint="http://127.0.0.1:8000/v1",
        gpu_viability="NOT_VERIFIED",
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["inference_mode"] == "local_only"
    assert body["gpu_viability"] == "NOT_VERIFIED"
    assert body["model_endpoint"].startswith("http://127.0.0.1")


def test_terminal_contract_exposes_every_frozen_state(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "asset.sqlite3")
    with TestClient(app) as client:
        response = client.get("/api/v1/contracts/terminal-states")
    assert response.status_code == 200
    assert set(response.json()["values"]) == {state.value for state in TerminalState}


def test_openapi_contains_reviewable_health_contract(tmp_path) -> None:
    document = create_app(database_path=tmp_path / "asset.sqlite3").openapi()
    operation = document["paths"]["/api/v1/health"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]
