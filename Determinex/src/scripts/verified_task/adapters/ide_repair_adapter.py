"""IDE-grade Java/C/C++ repair adapter.

This adapter is for tasks harvested from IDE benchmark suites, language-server
diagnostics, compiler traces, and project-local tests. It keeps the task shape
the same as every other verifier loop: workspace, instruction, diagnostics,
validation commands, and a pass/fail scorer.
"""

from __future__ import annotations

from pathlib import Path

from ..language_profiles import default_validation_commands
from ..task_spec import ResourceLimits, TaskSpec

IDE_LANGUAGES = {"java", "c", "cpp", "c++", "typescript", "javascript", "go", "rust", "python"}


def ide_repair_task_spec(
    *,
    task_id: str,
    language: str,
    workspace: Path,
    diagnostic: str,
    validation_commands: list[str] | None = None,
    ide_name: str = "",
    timeout_seconds: int = 1200,
) -> TaskSpec:
    key = language.strip().lower()
    if key not in IDE_LANGUAGES:
        raise ValueError(f"unsupported IDE repair language: {language}")
    normalized = "cpp" if key == "c++" else key
    return TaskSpec(
        id=task_id,
        benchmark="IDE-Repair",
        language=normalized,
        repo_or_workspace=str(workspace),
        instruction=diagnostic,
        validation_commands=validation_commands or default_validation_commands(normalized),
        scorer="all_commands_pass",
        privacy_policy="cloak",
        cloak_mode="project",
        resource_limits=ResourceLimits(
            timeout_seconds=timeout_seconds, max_attempts=4, docker_cpus=2
        ),
        metadata={"adapter": "ide_repair", "ide_name": ide_name, "task_shape": "diagnostic_repair"},
    )
