"""SWELancer bug/feature adapter."""

from __future__ import annotations

from pathlib import Path

from ..language_profiles import default_validation_commands
from ..task_spec import ResourceLimits, TaskSpec


def swelancer_task_spec(
    *,
    task_id: str,
    language: str,
    workspace: Path,
    work_order: str,
    task_kind: str = "bug",
    acceptance_commands: list[str] | None = None,
    dollar_value: float | None = None,
    timeout_seconds: int = 1800,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        benchmark="SWELancer",
        language=language,
        repo_or_workspace=str(workspace),
        instruction=work_order,
        validation_commands=acceptance_commands or default_validation_commands(language),
        scorer="all_commands_pass",
        privacy_policy="cloak",
        cloak_mode="project",
        resource_limits=ResourceLimits(
            timeout_seconds=timeout_seconds, max_attempts=5, docker_cpus=2
        ),
        metadata={
            "adapter": "swelancer",
            "task_shape": task_kind,
            "dollar_value": dollar_value,
        },
    )
