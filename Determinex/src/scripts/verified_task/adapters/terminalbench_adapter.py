"""Generic terminal/repo task adapter."""

from __future__ import annotations

from pathlib import Path

from ..language_profiles import default_validation_commands
from ..task_spec import ResourceLimits, TaskSpec


def terminal_task_spec(
    *,
    task_id: str,
    instruction: str,
    workspace: Path,
    validation_commands: list[str] | None = None,
    setup_commands: list[str] | None = None,
    language: str = "bash",
    timeout_seconds: int = 600,
    max_attempts: int = 3,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        benchmark="Terminal-Bench",
        language=language,
        repo_or_workspace=str(workspace),
        instruction=instruction,
        setup_commands=setup_commands or [],
        validation_commands=validation_commands or default_validation_commands(language),
        scorer="all_commands_pass",
        privacy_policy="local",
        resource_limits=ResourceLimits(
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            max_parallel=1,
        ),
    )
