"""BigCodeBench adapter placeholder for Python library tasks."""

from __future__ import annotations

from pathlib import Path

from ..task_spec import ResourceLimits, TaskSpec


def bigcodebench_task_spec(
    *,
    task_id: str,
    workspace: Path,
    prompt: str,
    test_command: str = "python -m pytest -q",
    timeout_seconds: int = 900,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        benchmark="BigCodeBench",
        language="python",
        repo_or_workspace=str(workspace),
        instruction=prompt,
        prompt=prompt,
        validation_commands=[test_command],
        scorer="all_commands_pass",
        privacy_policy="local",
        resource_limits=ResourceLimits(timeout_seconds=timeout_seconds, max_attempts=3),
        metadata={"adapter": "bigcodebench", "focus": "library_api_usage"},
    )
