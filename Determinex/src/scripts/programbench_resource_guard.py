#!/usr/bin/env python3
"""Resource guard for ProgramBench official evals.

ProgramBench tasks run inside Docker, but a single task can still fan out into
many processes because branch run scripts commonly use ``pytest -n auto`` and
some tools spawn subprocess-heavy tests. On Docker Desktop that can wedge the
daemon and leave the UI returning 500s.

This module is the law: Determinex-side callers build ProgramBench eval commands
through this guard instead of open-coding ``uv run programbench eval``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

RESOURCE_SENSITIVE_PATTERNS: tuple[str, ...] = (
    # Real timing benchmark. Its tests spawn pytest-xdist workers, and those
    # workers spawn measured subprocess workloads. This has crashed Docker
    # Desktop repeatedly when launched with default xdist fanout.
    "hyperfine",
)


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 64) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class ProgramBenchEvalPolicy:
    """Concrete resource policy for one ProgramBench eval invocation."""

    workers: int
    branch_workers: int
    docker_cpus: int
    timeout_seconds: int
    resource_sensitive: bool = False
    quarantined: bool = False
    reason: str = ""

    def flags(self) -> list[str]:
        return [
            "--workers",
            str(self.workers),
            "--branch-workers",
            str(self.branch_workers),
            "--docker-cpus",
            str(self.docker_cpus),
        ]


def is_resource_sensitive(*parts: str | Path | None) -> bool:
    """Return True when the instance/filter/path is known to be Docker-risky."""
    haystack = " ".join(str(p).lower() for p in parts if p is not None)
    if any(pat in haystack for pat in RESOURCE_SENSITIVE_PATTERNS):
        return True
    for part in parts:
        if part is None:
            continue
        try:
            path = Path(part)
        except TypeError:
            continue
        if not path.is_dir():
            continue
        try:
            for child in path.iterdir():
                name = child.name.lower()
                if any(pat in name for pat in RESOURCE_SENSITIVE_PATTERNS):
                    return True
        except OSError:
            continue
    return False


def policy_for_eval(
    *,
    instance_id: str = "",
    scaffold_root: str | Path | None = None,
    filter_re: str = "",
    requested_workers: int | None = None,
) -> ProgramBenchEvalPolicy:
    """Compute the only approved ProgramBench Docker resource policy.

    Environment overrides:
      DETERMINEX_PB_MAX_WORKERS          default 1, capped to 1 for one eval call
      DETERMINEX_PB_BRANCH_WORKERS       default 1, capped to 1
      DETERMINEX_PB_DOCKER_CPUS          default 1, capped to 1; bounds xdist auto workers
      DETERMINEX_PB_HEAVY_DOCKER_CPUS    default 1, for resource-sensitive tools
      DETERMINEX_PB_EVAL_TIMEOUT         default 1200 seconds
      DETERMINEX_PB_ALLOW_RESOURCE_RISK  set to 1 to run quarantined tools
    """
    sensitive = is_resource_sensitive(instance_id, scaffold_root, filter_re)
    max_workers = _env_int("DETERMINEX_PB_MAX_WORKERS", 1, minimum=1, maximum=1)
    if requested_workers is None:
        requested_workers = max_workers
    workers = max(1, min(requested_workers, max_workers))

    branch_workers = _env_int("DETERMINEX_PB_BRANCH_WORKERS", 1, minimum=1, maximum=1)
    # docker_cpus also sets PYTEST_XDIST_AUTO_NUM_WORKERS inside the container.
    # default = 1 (single xdist worker — NO fan-out — NO deadlock).
    # Setting to 2+ allows pytest-xdist to spawn parallel workers which deadlock
    # on stdin handshake for some tools (silver_searcher reproduces this every
    # run). Parallelism belongs one level above this guard: run multiple
    # independent eval calls, each with docker_cpus=1.
    docker_cpus = _env_int("DETERMINEX_PB_DOCKER_CPUS", 1, minimum=1, maximum=1)
    timeout = _env_int("DETERMINEX_PB_EVAL_TIMEOUT", 1200, minimum=60, maximum=7200)

    quarantined = False
    reason = ""
    if sensitive:
        workers = 1
        branch_workers = 1
        docker_cpus = _env_int("DETERMINEX_PB_HEAVY_DOCKER_CPUS", 1, minimum=1, maximum=1)
        timeout = _env_int("DETERMINEX_PB_HEAVY_TIMEOUT", 1800, minimum=300, maximum=7200)
        if os.environ.get("DETERMINEX_PB_ALLOW_RESOURCE_RISK", "").strip() != "1":
            quarantined = True
            reason = (
                "resource-sensitive ProgramBench tool: requires explicit "
                "DETERMINEX_PB_ALLOW_RESOURCE_RISK=1 and one-worker Docker lane"
            )

    return ProgramBenchEvalPolicy(
        workers=workers,
        branch_workers=branch_workers,
        docker_cpus=docker_cpus,
        timeout_seconds=timeout,
        resource_sensitive=sensitive,
        quarantined=quarantined,
        reason=reason,
    )


def build_eval_cmd(
    *,
    scaffold_root: str | Path,
    filter_re: str = "",
    force: bool = True,
    requested_workers: int | None = None,
    instance_id: str = "",
) -> tuple[list[str], ProgramBenchEvalPolicy]:
    """Build a guarded ``uv run programbench eval`` command."""
    policy = policy_for_eval(
        instance_id=instance_id,
        scaffold_root=scaffold_root,
        filter_re=filter_re,
        requested_workers=requested_workers,
    )
    cmd = [
        "uv",
        "run",
        "programbench",
        "eval",
        str(scaffold_root).replace("\\", "/"),
    ]
    if filter_re:
        cmd += ["--filter", filter_re]
    cmd += policy.flags()
    if force:
        cmd.append("--force")
    return cmd, policy


def describe_policy(policy: ProgramBenchEvalPolicy) -> str:
    bits = [
        f"workers={policy.workers}",
        f"branch_workers={policy.branch_workers}",
        f"docker_cpus={policy.docker_cpus}",
        f"timeout={policy.timeout_seconds}s",
    ]
    if policy.resource_sensitive:
        bits.append("resource_sensitive=1")
    if policy.quarantined:
        bits.append("QUARANTINED")
    return " ".join(bits)


def assert_no_unguarded_eval_command(command: Iterable[str]) -> None:
    """Test helper: verify a command includes the guard's required flags."""
    text = " ".join(command)
    if "programbench eval" not in text:
        return
    missing = [
        flag
        for flag in ("--workers", "--branch-workers", "--docker-cpus")
        if not re.search(rf"(^|\s){re.escape(flag)}(\s|$)", text)
    ]
    if missing:
        raise AssertionError(f"unguarded ProgramBench eval command missing {missing}: {text}")
