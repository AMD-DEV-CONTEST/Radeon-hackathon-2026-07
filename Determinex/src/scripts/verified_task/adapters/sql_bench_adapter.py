"""SQL/BIRD/BIRD-Critic style adapter."""

from __future__ import annotations

from pathlib import Path

from ..task_spec import ResourceLimits, TaskSpec


def sql_task_spec(
    *,
    task_id: str,
    benchmark: str,
    workspace: Path,
    question: str,
    execution_command: str = "python -m scripts.verified_task.sql_smoke",
    timeout_seconds: int = 300,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        benchmark=benchmark,
        language="sql",
        repo_or_workspace=str(workspace),
        instruction=question,
        validation_commands=[execution_command],
        scorer="all_commands_pass",
        privacy_policy="local",
        resource_limits=ResourceLimits(timeout_seconds=timeout_seconds, max_attempts=3),
        metadata={"adapter": "sql", "oracle": "execution_comparator"},
    )
