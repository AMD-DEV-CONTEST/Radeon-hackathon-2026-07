"""Deterministic patch and workspace verification for SWE tasks."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


CommandRunner = Callable[[str, int], Mapping[str, Any]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    exit_code: int
    output: str = ""
    command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "output": self.output,
            "command": self.command,
        }


@dataclass
class VerifierReport:
    verdict: str
    mode: str
    checks: list[CheckResult] = field(default_factory=list)
    targeted_tests: list[str] = field(default_factory=list)
    reproduction: dict[str, Any] | None = None
    failure_summary: str = ""
    llm_review: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.verdict == "accept"

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "mode": self.mode,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "targeted_tests": self.targeted_tests,
            "reproduction": self.reproduction,
            "failure_summary": self.failure_summary,
            "llm_review": self.llm_review,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def rank_verifier_reports(reports: Sequence[VerifierReport]) -> list[VerifierReport]:
    """Rank candidate patch reports using deterministic evidence only.

    This is the reusable scoring seam for an Agentless-style V4 experiment;
    candidate generation remains in the caller so its model-call budget is
    explicit and comparable.
    """
    def score(report: VerifierReport) -> tuple[int, int, int]:
        passed_checks = sum(check.passed for check in report.checks)
        reproduction = int(bool(report.reproduction and report.reproduction.get("discriminative")))
        return (int(report.passed), reproduction, passed_checks)

    return sorted(reports, key=score, reverse=True)


class CodeVerifier:
    """Run cheap deterministic gates before accepting a candidate patch.

    ``runner`` should execute commands inside the same environment as the
    coding agent.  Commands are never run through the host shell when a
    isolated execution environment is supplied.
    """

    def __init__(
        self,
        runner: CommandRunner,
        *,
        mode: str = "V1",
        max_targeted_tests: int = 3,
        command_timeout: int = 120,
    ) -> None:
        self.runner = runner
        self.mode = mode.upper()
        self.max_targeted_tests = max(0, max_targeted_tests)
        self.command_timeout = command_timeout

    def _run(self, name: str, command: str, timeout: int | None = None) -> CheckResult:
        result = self.runner(command, timeout or self.command_timeout)
        output = str(result.get("output", ""))
        exit_code = int(result.get("exit_code", result.get("returncode", 0)))
        return CheckResult(name, exit_code == 0, exit_code, output[-12000:], command)

    def _changed_files(self) -> list[str]:
        result = self.runner("git diff --name-only", 30)
        if int(result.get("exit_code", result.get("returncode", 0))) != 0:
            return []
        return [line.strip() for line in str(result.get("output", "")).splitlines() if line.strip()]

    def _targeted_test_paths(self, changed_files: Sequence[str]) -> list[str]:
        candidates: list[str] = []
        for changed in changed_files:
            path = Path(changed)
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                candidates.append(changed)
                continue
            stem = path.stem
            candidates.extend(
                [
                    str(path.with_name(f"test_{stem}.py")),
                    str(path.with_name(f"{stem}_test.py")),
                    f"tests/test_{stem}.py",
                ]
            )
        # Only run files that exist.  This command is executed in the task
        # environment, so the check is safe for Docker as well.
        existing: list[str] = []
        for candidate in dict.fromkeys(candidates):
            quoted = shlex.quote(candidate)
            check = self.runner(f"test -f {quoted}", 10)
            if int(check.get("exit_code", check.get("returncode", 0))) == 0:
                existing.append(candidate)
            if len(existing) >= self.max_targeted_tests:
                break
        return existing

    @staticmethod
    def _baseline_reproduction_command(command: str) -> str:
        """Run a reproduction command against a clean detached worktree."""
        quoted_command = shlex.quote(command)
        return (
            "tmp_dir=$(mktemp -d) && "
            "git worktree add --detach \"$tmp_dir\" HEAD >/dev/null 2>&1 && "
            "(cd \"$tmp_dir\" && sh -lc " + quoted_command + ") ; "
            "status=$?; git worktree remove --force \"$tmp_dir\" >/dev/null 2>&1 || true; "
            "rmdir \"$tmp_dir\" 2>/dev/null || true; exit $status"
        )

    def verify(
        self,
        *,
        patch: str | None = None,
        changed_files: Sequence[str] | None = None,
        reproduction_before: str | None = None,
        reproduction_after: str | None = None,
    ) -> VerifierReport:
        """Run the selected verification gates in a fixed order."""
        if self.mode == "V0":
            return VerifierReport("accept", self.mode)

        checks: list[CheckResult] = []
        if patch:
            delimiter = "__TRACK2_PATCH_EOF__"
            if delimiter in patch:
                checks.append(
                    CheckResult(
                        "patch_apply_check",
                        False,
                        2,
                        "patch contains reserved delimiter",
                        "",
                    )
                )
            else:
                patch_command = f"cat <<'{delimiter}' | git apply --check -\n{patch}\n{delimiter}"
                checks.append(self._run("patch_apply_check", patch_command))
        checks.append(self._run("diff_check", "git diff --check"))
        changed = list(changed_files or self._changed_files())
        if not changed:
            checks.append(
                CheckResult(
                    "changes_present",
                    False,
                    1,
                    "workspace has no changed files",
                    "git diff --name-only",
                )
            )
        python_files = [path for path in changed if path.endswith(".py")]
        if python_files:
            command = "python3 -m py_compile " + " ".join(shlex.quote(path) for path in python_files[:40])
            checks.append(self._run("python_compile", command))

        targeted_tests: list[str] = []
        if self.mode in {"V2", "V3", "V4", "V5"}:
            targeted_tests = self._targeted_test_paths(changed)
            if targeted_tests:
                command = "python3 -m pytest -q " + " ".join(shlex.quote(path) for path in targeted_tests)
                checks.append(self._run("targeted_tests", command, max(self.command_timeout, 300)))

        reproduction: dict[str, Any] | None = None
        if self.mode in {"V3", "V4", "V5"} and reproduction_before and reproduction_after:
            before = self._run(
                "reproduction_before",
                self._baseline_reproduction_command(reproduction_before),
                max(self.command_timeout, 300),
            )
            after = self._run("reproduction_after", reproduction_after, max(self.command_timeout, 300))
            reproduction = {
                "before": "fail" if not before.passed else "pass",
                "after": "pass" if after.passed else "fail",
                "discriminative": (not before.passed) and after.passed,
            }
            checks.extend([before, after])

        # A reproduction-before check is expected to fail; it is evidence for
        # a discriminative regression test, not a rejection gate by itself.
        failed = [
            check
            for check in checks
            if not check.passed and check.name != "reproduction_before"
        ]
        if reproduction is not None and not reproduction["discriminative"]:
            failure_summary = "reproduction test was not discriminative"
        elif failed:
            failure_summary = "; ".join(f"{check.name}: {check.output[-500:]}" for check in failed)
        else:
            failure_summary = ""
        return VerifierReport(
            "reject" if failed or (reproduction is not None and not reproduction["discriminative"]) else "accept",
            self.mode,
            checks,
            targeted_tests,
            reproduction,
            failure_summary,
        )
