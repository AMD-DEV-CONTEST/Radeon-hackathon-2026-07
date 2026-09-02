"""Stage E — Full run lifecycle API tests (progress, list, cancel, retry)."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import RunState, RunStatus
from app.services.runs import (
    _write_state,
    _run_path,
    cancel_run,
    retry_run,
    dispatch_background_run,
    list_runs,
    list_all_runs,
    build_progress,
    RunNotFoundError,
    RunAlreadyExecutedError,
    RunWrongStatusError,
    RunCancelTooLateError,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
    )


def _setup_project(client: TestClient) -> None:
    assert client.post(
        "/api/projects", json={"project_id": "demo-project", "name": "Demo"}
    ).status_code == 201


# ── API: Create + List runs ─────────────────────────────────────────────────


def test_list_project_runs(tmp_path: Path) -> None:
    """GET /api/projects/{project_id}/runs returns all runs, newest first."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _setup_project(client)

        # Create 2 runs
        r1 = client.post("/api/projects/demo-project/runs").json()
        r2 = client.post("/api/projects/demo-project/runs").json()

        runs = client.get("/api/projects/demo-project/runs").json()
        assert len(runs) >= 2
        # Newest first
        assert runs[0]["run_id"] == r2["run_id"]
        assert runs[1]["run_id"] == r1["run_id"]


def test_list_all_runs_global(tmp_path: Path) -> None:
    """GET /api/runs returns all runs across projects."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _setup_project(client)
        r1 = client.post("/api/projects/demo-project/runs").json()

        global_runs = client.get("/api/runs").json()
        assert any(r["run_id"] == r1["run_id"] for r in global_runs)


# ── API: Progress ────────────────────────────────────────────────────────────


def test_progress_endpoint_returns_run_progress(tmp_path: Path) -> None:
    """GET /api/projects/{pid}/runs/{rid}/progress returns structured progress."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/projects/demo-project/runs").json()
        rid = created["run_id"]

        progress = client.get(f"/api/projects/demo-project/runs/{rid}/progress").json()
        assert progress["run_id"] == rid
        assert progress["status"] == "queued"
        assert progress["current_step"] == 0
        assert progress["percentage"] == 0
        assert "timing_by_step" in progress
        assert isinstance(progress["timing_by_step"], list)


def test_progress_404_on_missing_run(tmp_path: Path) -> None:
    """Progress endpoint returns 404 for unknown run."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        # Use a valid 32-char hex that doesn't exist
        assert client.get("/api/projects/demo-project/runs/00000000000000000000000000000001/progress").status_code == 404


# ── API: Cancel ──────────────────────────────────────────────────────────────


def test_cancel_queued_run(tmp_path: Path) -> None:
    """DELETE a queued run sets it to cancelled."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/projects/demo-project/runs").json()
        rid = created["run_id"]

        cancelled = client.delete(f"/api/projects/demo-project/runs/{rid}").json()
        assert cancelled["status"] == "cancelled"
        assert cancelled["cancel_requested"] is True
        assert cancelled["completed_at"] is not None


def test_cancel_completed_run_fails(tmp_path: Path) -> None:
    """Cannot cancel a completed run (409)."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/projects/demo-project/runs").json()
        rid = created["run_id"]

        # Manually mark as completed
        from app.services.runs import get_run, save_run
        state = get_run(settings, "demo-project", rid)
        state = state.model_copy(update={"status": RunStatus.COMPLETED, "completed_at": datetime.now(UTC)})
        save_run(settings, state)

        resp = client.delete(f"/api/projects/demo-project/runs/{rid}")
        assert resp.status_code == 409


def test_cancel_non_existent_run(tmp_path: Path) -> None:
    """Cancel non-existent run returns 404."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        assert client.delete("/api/projects/demo-project/runs/00000000000000000000000000000002").status_code == 404


# ── API: Retry ───────────────────────────────────────────────────────────────


def test_retry_failed_run_creates_new_queued_run(tmp_path: Path) -> None:
    """Retrying a failed run creates a new queued run with incremented retry_count."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/projects/demo-project/runs").json()
        rid = created["run_id"]

        # Mark as failed
        from app.services.runs import get_run, save_run
        state = get_run(settings, "demo-project", rid)
        state = state.model_copy(update={"status": RunStatus.FAILED, "error": "test failure"})
        save_run(settings, state)

        retried = client.post(f"/api/projects/demo-project/runs/{rid}/retry").json()
        assert retried["status"] == "queued"
        assert retried["retry_count"] == 1
        assert retried["run_id"] != rid


def test_retry_non_failed_run_fails(tmp_path: Path) -> None:
    """Cannot retry a queued or completed run (400)."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/projects/demo-project/runs").json()
        rid = created["run_id"]

        # It's queued, not failed — should fail
        resp = client.post(f"/api/projects/demo-project/runs/{rid}/retry")
        assert resp.status_code == 400


# ── Service: build_progress ──────────────────────────────────────────────────


def test_build_progress_from_runstate(tmp_path: Path) -> None:
    """build_progress returns correct RunProgress for a RunState."""
    now = datetime.now(UTC)
    state = RunState(
        run_id="a" * 32,
        project_id="demo-project",
        status=RunStatus.SCANNING,
        current_step=2,
        total_steps=8,
        created_at=now,
        updated_at=now,
    )
    progress = build_progress(state)
    assert progress.run_id == "a" * 32
    assert progress.status == RunStatus.SCANNING
    assert progress.percentage == 25
    assert progress.current_step == 2
    assert progress.current_step_name in ("scanning", "scan")


def test_build_progress_completed_100_percent(tmp_path: Path) -> None:
    """Completed run shows 100% progress."""
    now = datetime.now(UTC)
    state = RunState(
        run_id="b" * 32,
        project_id="demo-project",
        status=RunStatus.COMPLETED,
        current_step=8,
        total_steps=8,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    progress = build_progress(state)
    assert progress.percentage == 100


# ── API: No duplicate execution ─────────────────────────────────────────────


def test_execute_already_executed_run_returns_409(tmp_path: Path) -> None:
    """POST /execute on a non-queued run returns 409 conflict."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/projects/demo-project/runs").json()
        rid = created["run_id"]

        # Execute once
        first = client.post(f"/api/projects/demo-project/runs/{rid}/execute")
        assert first.status_code == 202

        # Wait briefly for background task
        import time
        time.sleep(1)

        # Try to execute again
        resp = client.post(f"/api/projects/demo-project/runs/{rid}/execute")
        # Should be 409 (already executed) or the run is still running
        assert resp.status_code == 409


# ── API: download artifact still works ─────────────────────────────────────


def test_download_artifact_with_error_codes(tmp_path: Path) -> None:
    """Artifact download endpoint returns unified error codes on failure."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)

        # Unknown run
        resp = client.get("/api/projects/demo-project/runs/00000000000000000000000000000003/artifacts/result")
        assert resp.status_code == 404
        detail = resp.json().get("detail", {})
        assert isinstance(detail, dict)
        assert "error_code" in detail
