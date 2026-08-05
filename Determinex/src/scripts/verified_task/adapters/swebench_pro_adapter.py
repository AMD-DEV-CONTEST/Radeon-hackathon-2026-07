"""SWE-bench Pro / multilingual repo-repair adapter."""

from __future__ import annotations

from pathlib import Path

from ..language_profiles import default_validation_commands
from ..task_spec import ResourceLimits, TaskSpec


def swebench_pro_task_spec(
    *,
    task_id: str,
    language: str,
    workspace: Path,
    issue_text: str,
    test_commands: list[str] | None = None,
    allowed_files: list[str] | None = None,
    cloak_mode: str = "project",
    timeout_seconds: int = 1800,
) -> TaskSpec:
    """Create a repo-repair TaskSpec for SWE-bench-like tasks."""
    return TaskSpec(
        id=task_id,
        benchmark="SWE-bench Pro",
        language=language,
        repo_or_workspace=str(workspace),
        instruction=issue_text,
        allowed_files=allowed_files or [],
        validation_commands=test_commands or default_validation_commands(language),
        scorer="all_commands_pass",
        privacy_policy="cloak",
        cloak_mode=cloak_mode,
        resource_limits=ResourceLimits(
            timeout_seconds=timeout_seconds, max_attempts=5, docker_cpus=2
        ),
        metadata={"adapter": "swebench_pro", "task_shape": "repo_repair"},
    )
