from datetime import date, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.schemas import Evidence, TaskStatus
from app.services.phase_c import evaluate_tasks, load_tasks, render_reports


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
    )


def _write_tasks(settings: Settings) -> None:
    source = settings.project_root / "demo-project" / "source"
    source.mkdir(parents=True)
    (source / "tasks.csv").write_text(
        "title,assignee,deadline,priority,acceptance_criteria,original_source\n"
        "API verification,Ada,"
        f"{(date.today() + timedelta(days=30)).isoformat()},high,test report,weekly plan\n",
        encoding="utf-8",
    )


def test_load_tasks_is_project_scoped_and_returns_public_tasks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_tasks(settings)

    tasks = load_tasks("demo-project", settings=settings)

    assert len(tasks) == 1
    assert tasks[0].task_id.startswith("task-")
    assert tasks[0].owner == "Ada"
    assert tasks[0].due_date == date.today() + timedelta(days=30)

    derived = settings.project_root / "demo-project" / "derived"
    derived.mkdir()
    (derived / "tasks.csv").write_text("title,assignee\nUnsafe,Ada\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source directory"):
        load_tasks("demo-project", settings=settings, task_relative_path="../derived/tasks.csv")
    with pytest.raises(ValueError):
        load_tasks("demo-project", settings=settings, task_relative_path="../../outside.csv")


def test_phase_c_adapters_preserve_evidence_and_render_a_public_report(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_tasks(settings)
    task = load_tasks("demo-project", settings=settings)[0]
    evidence = Evidence(
        evidence_id="evidence-1",
        relative_path="source/status.md",
        locator="## API",
        excerpt="API verification completed and the test report is available.",
        score=0.92,
    )

    evaluations = evaluate_tasks([task], {task.task_id: [evidence]})
    assert evaluations[0].status is TaskStatus.COMPLETED
    assert evaluations[0].evidence == [evidence]

    draft = render_reports("demo-project", evaluations)
    assert draft.project_id == "demo-project"
    assert "source/status.md" in draft.markdown
    assert "completed" in draft.markdown
