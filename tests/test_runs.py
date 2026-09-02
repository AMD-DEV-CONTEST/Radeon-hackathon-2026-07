import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.runner import ControlledRunner
from app.config import Settings
from app.observability.audit import AuditTrail
from app.main import create_app
from app.schemas import RunState, RunStatus
from app.services.runs import save_run


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
    )


def _queued_state() -> RunState:
    now = datetime.now(UTC)
    return RunState(
        run_id="a" * 32,
        project_id="demo-project",
        created_at=now,
        updated_at=now,
    )


def test_run_api_persists_a_project_scoped_queued_run(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post(
            "/api/projects", json={"project_id": "demo-project", "name": "Demo"}
        ).status_code == 201

        created = client.post("/api/projects/demo-project/runs")
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "queued"
        assert body["current_step"] == 0

        read_back = client.get(f"/api/projects/demo-project/runs/{body['run_id']}")
        assert read_back.status_code == 200
        assert read_back.json()["run_id"] == body["run_id"]

        assert client.get(f"/api/projects/other-project/runs/{body['run_id']}").status_code == 404
        assert client.get("/api/projects/demo-project/runs/not-a-run-id").status_code == 422

    persisted = list((settings.output_root / "demo-project" / "runs").glob("*.json"))
    assert len(persisted) == 1


def test_run_artifacts_are_downloadable_only_by_known_names(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post(
            "/api/projects", json={"project_id": "demo-project", "name": "Demo"}
        ).status_code == 201
        created = client.post("/api/projects/demo-project/runs").json()
        run_id = created["run_id"]
        result_path = settings.output_root / "demo-project" / "results" / f"{run_id}.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_text('{"evaluations": []}', encoding="utf-8")
        save_run(
            settings,
            RunState.model_validate(
                {**created, "artifacts": {"result": f"results/{run_id}.json"}}
            ),
        )

        downloaded = client.get(f"/api/projects/demo-project/runs/{run_id}/artifacts/result")
        assert downloaded.status_code == 200
        assert downloaded.json() == {"evaluations": []}
        assert client.get(f"/api/projects/demo-project/runs/{run_id}/artifacts/../../runs").status_code in {404, 422}


def test_controlled_runner_uses_only_the_fixed_registered_pipeline(tmp_path: Path) -> None:
    calls: list[str] = []

    def tool(name: str):
        def invoke(_context):
            calls.append(name)
            return {"tool": name}

        return invoke

    audit = AuditTrail(tmp_path, "a" * 32)
    runner = ControlledRunner(
        {name: tool(name) for name in ("scan", "index", "retrieve", "evaluate", "draft")},
        audit,
    )
    result = runner.run(_queued_state())

    assert result.status is RunStatus.COMPLETED
    assert result.current_step == 5
    assert calls == ["scan", "index", "retrieve", "evaluate", "draft"]
    events = [json.loads(line)["event"] for line in audit.path.read_text(encoding="utf-8").splitlines()]
    assert events[0] == "run_started"
    assert events[-1] == "run_completed"


def test_controlled_runner_fails_for_missing_tool_or_step_limit(tmp_path: Path) -> None:
    audit = AuditTrail(tmp_path, "b" * 32)
    missing = ControlledRunner({"scan": lambda _context: {}}, audit)
    failed = missing.run(_queued_state())
    assert failed.status is RunStatus.FAILED
    assert failed.error == "required tool is not registered: index"

    tools = {name: (lambda _context: {}) for name in ("scan", "index", "retrieve", "evaluate", "draft")}
    limited = ControlledRunner(tools, AuditTrail(tmp_path, "c" * 32), max_steps=3)
    capped = limited.run(_queued_state())
    assert capped.status is RunStatus.FAILED
    assert capped.current_step == 3
    assert capped.error == "maximum step count reached"
