from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas import Evidence, Task, TaskEvaluation
from app.schemas.models import TaskStatus
from app.security.paths import validate_project_id


def test_project_id_requires_safe_lowercase_identifier() -> None:
    assert validate_project_id("demo-project-1") == "demo-project-1"
    with pytest.raises(ValueError):
        validate_project_id("../outside")
    with pytest.raises(ValueError):
        validate_project_id("Demo Project")


def test_task_evaluation_requires_explicit_evidence_contract() -> None:
    task = Task(task_id="task-1", title="Run system test", due_date=date(2026, 7, 21))
    evidence = Evidence(
        evidence_id="ev-1",
        relative_path="status.md",
        locator="## Testing",
        excerpt="The regression suite passed.",
        score=0.9,
    )
    evaluation = TaskEvaluation(
        task_id=task.task_id,
        status=TaskStatus.MOSTLY_COMPLETED,
        explanation="Regression evidence exists but final approval is absent.",
        evidence=[evidence],
        missing_evidence=["final approval"],
    )
    assert evaluation.evidence[0].relative_path == "status.md"

    with pytest.raises(ValidationError):
        Evidence(evidence_id="ev-2", relative_path="x", locator="p1", excerpt="x", score=1.1)
