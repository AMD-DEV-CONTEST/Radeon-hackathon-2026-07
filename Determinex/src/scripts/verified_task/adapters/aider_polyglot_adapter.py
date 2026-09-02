"""Aider Polyglot / Exercism-style adapter into TaskSpec."""

from __future__ import annotations

from pathlib import Path

from ..language_profiles import default_validation_commands
from ..task_spec import ResourceLimits, TaskSpec


def aider_polyglot_task_spec(
    *,
    task_id: str,
    language: str,
    workspace: Path,
    problem_statement: str,
    test_commands: list[str] | None = None,
    timeout_seconds: int = 900,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        benchmark="Aider-Polyglot",
        language=language,
        repo_or_workspace=str(workspace),
        instruction=problem_statement,
        validation_commands=test_commands or default_validation_commands(language),
        scorer="all_commands_pass",
        privacy_policy="local",
        resource_limits=ResourceLimits(timeout_seconds=timeout_seconds, max_attempts=2),
        metadata={"adapter": "aider_polyglot"},
    )
