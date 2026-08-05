"""ProgramBench adapter into the universal TaskSpec contract."""

from __future__ import annotations

from pathlib import Path

from ..task_spec import ResourceLimits, TaskSpec


def programbench_task_spec(
    *,
    instance_id: str,
    candidate_root: Path,
    programbench_root: Path = Path("T:/Dev/ProgramBench"),
    workers: int = 1,
    docker_cpus: int = 1,
    timeout_seconds: int = 7200,
) -> TaskSpec:
    author = instance_id.split("__", 1)[0]
    command = (
        f'cd /d "{programbench_root}" && '
        f'PYTHONUTF8=1 uv run programbench eval "{candidate_root}" '
        f'--filter "{author}" --workers {workers} --branch-workers 1 '
        f"--docker-cpus {docker_cpus} --force"
    )
    return TaskSpec(
        id=instance_id,
        benchmark="ProgramBench",
        language="mixed-cli",
        repo_or_workspace=str(candidate_root),
        instruction=f"Rebuild ProgramBench CLI task {instance_id} and pass official eval.",
        validation_commands=[command],
        scorer="programbench_passed_total",
        privacy_policy="local-or-remote-worker",
        resource_limits=ResourceLimits(
            timeout_seconds=timeout_seconds,
            max_attempts=1,
            max_parallel=1,
            docker_cpus=docker_cpus,
        ),
        metadata={
            "programbench_root": str(programbench_root),
            "candidate_root": str(candidate_root),
            "filter": author,
        },
    )
