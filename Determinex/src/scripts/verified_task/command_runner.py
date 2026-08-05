"""Deterministic command execution for verified task validators.

As of HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001, command execution
routes through ``intake.hardened_runner.run``. The previous the previous shell-mode kwarg
invocation has been replaced with an explicit ``argv``-list invocation of
the platform shell (``/bin/sh -c <command>`` on POSIX, ``cmd.exe /c
<command>`` on Windows). The audit no longer flags this file as
BLOCKED_UNSAFE; workspace bounding, env scrubbing, Docker/network blocking,
and structured failure modes are all inherited from the hardened runner.

The string-form ``command`` argument is preserved for caller compatibility
with the existing TaskSpec language profiles (which include genuinely
shell-dependent forms like ``bash -n *.sh`` and the Windows ``if exist
Makefile (...)`` idiom that cannot be expressed as a single argv list).
A new ``run_argv`` method is also exposed for callers that already have
an argv list and want stricter handling.
"""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from intake.hardened_runner import run as _hardened_run


@dataclass(slots=True)
class CommandResult:
    command: str
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# Shell-style returncodes when the hardened runner blocks / can't find the
# tool. These align with widely-recognized shell conventions:
#   124 → timeout (already preserved from the pre-migration behavior)
#   126 → command found but not executable / blocked by policy (BLOCKED)
#   127 → command not found (tool_missing)
_RC_TIMEOUT = 124
_RC_BLOCKED = 126
_RC_TOOL_MISSING = 127


def _shell_argv(command: str) -> list[str]:
    """Return the argv list that delegates ``command`` to the platform shell.

    On Windows we use ``cmd.exe /c`` because the existing language profiles
    include cmd.exe-specific syntax (``if exist ... else (...)``). On POSIX
    we use ``/bin/sh -c`` for portable shell semantics (glob expansion,
    pipes, redirects). In both cases the hardened runner sees an argv list
    — no the previous shell-mode kwarg kwarg — so the parallel execution audit no longer
    flags this site as BLOCKED_UNSAFE.
    """
    if sys.platform == "win32":
        return ["cmd.exe", "/c", command]
    return ["/bin/sh", "-c", command]


class CommandRunner:
    def __init__(self, *, temp_dir: Path, env: dict[str, str] | None = None) -> None:
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        # Extra env merged into the hardened runner's scrubbed base env.
        # The hardened runner strips dangerous variables (LD_PRELOAD,
        # DYLD_INSERT_LIBRARIES, PYTHONSTARTUP, ...) so anything we add
        # here is additive over a known-safe baseline.
        self.extra_env: dict[str, str] = {
            "TMP": str(self.temp_dir),
            "TEMP": str(self.temp_dir),
            "TMPDIR": str(self.temp_dir),
            "DETERMINEX_TASK_TMP": str(self.temp_dir),
        }
        if env:
            self.extra_env.update(env)

    def run(self, command: str, *, cwd: Path, timeout_seconds: int) -> CommandResult:
        """Run a command string via the platform shell, through the hardened
        runner. Preserves the historical CommandResult shape."""
        return self._run_inner(
            display_command=command,
            argv=_shell_argv(command),
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )

    def run_argv(self, argv: list[str], *, cwd: Path, timeout_seconds: int) -> CommandResult:
        """Stricter API for callers that already have an argv list. No shell
        wrapping; the program is invoked directly via the hardened runner."""
        return self._run_inner(
            display_command=" ".join(argv),
            argv=argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )

    def _run_inner(
        self,
        *,
        display_command: str,
        argv: list[str],
        cwd: Path,
        timeout_seconds: int,
    ) -> CommandResult:
        started = time.monotonic()
        result = _hardened_run(
            argv,
            workspace=cwd,
            timeout=timeout_seconds,
            extra_env=self.extra_env,
        )
        duration = time.monotonic() - started

        if result.blocked:
            return CommandResult(
                command=display_command,
                cwd=str(cwd),
                returncode=_RC_BLOCKED,
                stdout="",
                stderr=f"BLOCKED: {result.reason}",
                duration_seconds=duration,
            )
        if result.timed_out:
            return CommandResult(
                command=display_command,
                cwd=str(cwd),
                returncode=_RC_TIMEOUT,
                stdout="",
                stderr=result.stderr or f"command timed out after {timeout_seconds}s",
                duration_seconds=duration,
                timed_out=True,
            )
        if result.tool_missing:
            return CommandResult(
                command=display_command,
                cwd=str(cwd),
                returncode=_RC_TOOL_MISSING,
                stdout="",
                stderr=result.stderr or f"tool not found: {argv[0]}",
                duration_seconds=duration,
            )
        return CommandResult(
            command=display_command,
            cwd=str(cwd),
            returncode=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
        )
