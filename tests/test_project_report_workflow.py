from pathlib import Path

from app.config import Settings
from app.rag.indexer import ProjectIndex
from app.schemas import ProjectCreate, RunStatus
from app.services.projects import create_project, project_paths
from app.services.runs import create_run, execute_project_report_run


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
    )


def test_controlled_run_executes_real_import_index_retrieval_and_report_locally(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    project = create_project(
        settings.project_root,
        settings.output_root,
        ProjectCreate(project_id="demo-project", name="Demo project"),
    )
    source = project_paths(settings.project_root, settings.output_root, project.project_id)["source"]
    (source / "tasks.csv").write_text(
        "title,assignee,deadline,priority,acceptance_criteria,original_source\n"
        "API verification,Ada,2026-12-31,high,test report,weekly plan\n",
        encoding="utf-8",
    )
    (source / "status.md").write_text(
        "# API verification\nAPI verification is completed and the test report is available.\n",
        encoding="utf-8",
    )

    queued = create_run(settings, project.project_id)
    result = execute_project_report_run(
        settings,
        project.project_id,
        queued.run_id,
        index_factory=lambda project_id, runtime: ProjectIndex(project_id, runtime, mock_embed_dim=32),
        use_llm=False,
        retrieval_min_score=0,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.current_step == 5
    assert result.artifacts["imported_files"] == "1"
    assert result.artifacts["tasks_evaluated"] == "1"
    report_path = settings.output_root / project.project_id / result.artifacts["report"]
    report = report_path.read_text(encoding="utf-8")
    assert "status.md" in report
    assert "completed" in report
    risk_path = settings.output_root / project.project_id / result.artifacts["risk_csv"]
    assert risk_path.is_file()
    assert "task_title" in risk_path.read_text(encoding="utf-8")
    plan_path = settings.output_root / project.project_id / result.artifacts["next_week_plan"]
    assert plan_path.is_file()
    assert "草案" in plan_path.read_text(encoding="utf-8")
    result_path = settings.output_root / project.project_id / result.artifacts["result"]
    assert result_path.is_file()
    assert "evaluations" in result_path.read_text(encoding="utf-8")
    audit = settings.log_root / "runs" / f"{queued.run_id}.jsonl"
    assert audit.is_file()
    assert '"event": "run_completed"' in audit.read_text(encoding="utf-8")
