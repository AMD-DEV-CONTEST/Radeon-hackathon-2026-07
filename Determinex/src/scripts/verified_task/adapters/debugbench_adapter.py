"""DebugBench-style bug repair adapter."""

from __future__ import annotations

from pathlib import Path

from ..language_profiles import default_validation_commands
from ..task_spec import ResourceLimits, TaskSpec


def debugbench_task_spec(
    *,
    task_id: str,
    language: str,
    workspace: Path,
    bug_report: str,
    test_commands: list[str] | None = None,
    timeout_seconds: int = 1200,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        benchmark="DebugBench",
        language=language,
        repo_or_workspace=str(workspace),
        instruction=bug_report,
        validation_commands=test_commands or default_validation_commands(language),
        scorer="all_commands_pass",
        privacy_policy="local",
        resource_limits=ResourceLimits(timeout_seconds=timeout_seconds, max_attempts=3),
        metadata={"adapter": "debugbench"},
    )
