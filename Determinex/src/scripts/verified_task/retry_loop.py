"""Generate -> validate -> repair -> ingest loop for TaskSpec."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .command_runner import CommandRunner
from .corpus_writer import CorpusWriter
from .task_spec import TaskSpec
from .verdict_recorder import atomic_write_json
from .workspace_manager import WorkspaceLease

RepairHook = Callable[[TaskSpec, WorkspaceLease, "AttemptRecord"], str | None]


@dataclass(slots=True)
class AttemptRecord:
    attempt_index: int
    verdict: str
    commands: list[dict[str, object]]
    failure_class: str | None = None
    repair_prompt: str | None = None
    patch_summary: str | None = None
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RetryLoopResult:
    passed: bool
    attempts: list[AttemptRecord]
    final_verdict_path: Path


class RetryLoop:
    def __init__(self, *, corpus_writer: CorpusWriter | None = None) -> None:
        self.corpus_writer = corpus_writer

    def run(
        self,
        spec: TaskSpec,
        lease: WorkspaceLease,
        *,
        repair_hook: RepairHook | None = None,
    ) -> RetryLoopResult:
        spec.validate()
        attempts: list[AttemptRecord] = []
        runner = CommandRunner(temp_dir=lease.temp)
        max_attempts = max(1, spec.resource_limits.max_attempts)

        for attempt_index in range(1, max_attempts + 1):
            commands = []
            for command in [*spec.setup_commands, *spec.validation_commands]:
                result = runner.run(
                    command,
                    cwd=lease.workspace,
                    timeout_seconds=spec.resource_limits.timeout_seconds,
                )
                commands.append(result.to_dict())
                if not result.ok:
                    break

            passed = bool(commands) and all(bool(c.get("returncode") == 0) for c in commands)
            failure_class = None if passed else self._classify_failure(commands)
            attempt = AttemptRecord(
                attempt_index=attempt_index,
                verdict="pass" if passed else "fail",
                commands=commands,
                failure_class=failure_class,
            )
            attempts.append(attempt)

            if self.corpus_writer:
                self.corpus_writer.write_attempt(
                    spec=spec,
                    attempt_index=attempt_index,
                    action_summary="validator run",
                    validator_results=commands,
                    verdict=attempt.verdict,
                    failure_class=failure_class,
                )

            if passed:
                break
            if repair_hook is None or attempt_index >= max_attempts:
                break
            repair = repair_hook(spec, lease, attempt)
            attempt.repair_prompt = repair
            if not repair:
                break

        out = lease.logs / "verified_task_result.json"
        atomic_write_json(
            out,
            {
                "task": spec.to_dict(),
                "passed": attempts[-1].verdict == "pass" if attempts else False,
                "attempts": [a.to_dict() for a in attempts],
            },
        )
        return RetryLoopResult(
            passed=attempts[-1].verdict == "pass" if attempts else False,
            attempts=attempts,
            final_verdict_path=out,
        )

    def _classify_failure(self, commands: list[dict[str, object]]) -> str:
        text = "\n".join(
            str(c.get("stderr", "")) + "\n" + str(c.get("stdout", "")) for c in commands
        ).lower()
        if "timed out" in text or "timeout" in text:
            return "timeout"
        if "syntaxerror" in text or "parse error" in text:
            return "syntax"
        if (
            "modulenotfounderror" in text
            or "no module named" in text
            or "cannot find module" in text
        ):
            return "dependency_import"
        if "assert" in text or "expected" in text or "actual" in text:
            return "wrong_output"
        if "permission denied" in text:
            return "permission"
        return "validator_failure"
