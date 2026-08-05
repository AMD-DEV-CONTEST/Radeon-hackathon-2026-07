"""scripts/intake/hardened_runner.py — bounded execution for intake.

The hardened runner used by ``BuildAdapter._run`` and ``ShadowCompiler`` as
of ``HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001``. Every subprocess invocation
from the arbitrary-repo intake path routes through ``run()`` below.

Guarantees (verified by ``tests/intake/test_hardened_intake_execution_runner_lock.py``):

  * Command MUST be ``list[str]`` — shell strings are rejected.
  * ``shell=True`` semantics are never available (the subprocess call below
    always passes ``shell=False`` explicitly).
  * ``cwd`` MUST resolve inside the supplied ``workspace`` root — path
    escape is rejected.
  * ``timeout`` MUST be a positive int; an upper sanity cap of 600 seconds
    is enforced regardless of what the caller asks for.
  * Docker / container runtimes (``docker``, ``docker-compose``,
    ``podman``, ``buildah``, ``kubectl``, ``helm``) are refused by default.
    Callers must pass ``allow_docker=True`` to opt in — and the
    Claude lane never sets that.
  * Network-enabling commands (``curl``, ``wget``, ``ncat``, ``netcat``)
    are refused by default. ``allow_network=True`` opts in.
  * The child process inherits a SCRUBBED environment: known code-injection
    vectors (``LD_PRELOAD``, ``LD_LIBRARY_PATH``, ``DYLD_*``,
    ``PYTHONSTARTUP``, ``PYTHONHOME``, ``IFS``, ``PS4``, ``BASH_ENV``,
    ``ENV``, ``FCEDIT``, ``TMPPREFIX``) are stripped unconditionally.
  * Every failure mode (missing tool, timeout, permission error,
    blocked-by-guard) is returned as a structured ``RunResult`` field —
    ``run()`` never raises into the caller.

NOT guaranteed (audited 2026-07-01, documented rather than silently assumed
covered — see docs/SECURITY_POSTURE.md "Hardened Runner — Actual Boundary"):

  * Network isolation is an argv[0] denylist, not a real network namespace
    or firewall rule. A general-purpose interpreter (python/node/bash/
    powershell/...) invoked to run untrusted code can still make arbitrary
    HTTP/socket calls — the denylist only catches invocations where the
    program itself IS a dedicated network tool (curl, ssh, dig, ...).
    Interpreters are deliberately not denylisted, since intake/build/repair
    legitimately needs them.
  * Filesystem isolation only covers ``cwd`` (validated inside
    ``workspace``). Command *arguments* referencing absolute paths outside
    the workspace are not validated — there is no argument-level path-escape
    check.
  * No OS-level resource limits (no ulimit/cgroup, no Windows Job Object).
    Only a wall-clock timeout is enforced; a fork bomb or memory-exhausting
    child process is not capped. (Contrast with ``hive/compiler.py``'s
    Compiler Oracle subprocess path, which does use a Windows Job Object
    with real resource limits — a different subsystem from this one.)

For anything that needs a real boundary against these gaps, use Docker
(as SWE-bench already does), not this runner alone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Public closed sets
# ---------------------------------------------------------------------------

# Environment variables stripped from every child invocation. These are the
# classic "library injection" / shell-startup hooks. Stripping is
# unconditional — there is no opt-in.
BLOCKED_ENV_VARS: Final[frozenset[str]] = frozenset(
    {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_FORCE_FLAT_NAMESPACE",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "IFS",
        "PS4",
        "BASH_ENV",
        "ENV",
        "FCEDIT",
        "TMPPREFIX",
        "PROMPT_COMMAND",
    }
)

# First-argv programs we refuse by default.
REFUSED_PROGRAMS: Final[frozenset[str]] = frozenset(
    {
        "docker",
        "docker.exe",
        "docker-compose",
        "docker-compose.exe",
        "podman",
        "podman.exe",
        "buildah",
        "buildah.exe",
        "kubectl",
        "kubectl.exe",
        "helm",
        "helm.exe",
    }
)

# First-argv programs that imply network egress, refused by default. This is
# a best-effort argv[0] denylist, not real network isolation (no namespace /
# firewall rule backs it) — see the "Actual Boundary" note in
# docs/SECURITY_POSTURE.md. Deliberately limited to programs whose ENTIRE
# purpose is network I/O; general-purpose interpreters/shells (python, node,
# bash, powershell, ...) are NOT here because intake/build/repair legitimately
# needs them, and a script-language process making an HTTP call is invisible
# to an argv[0] check no matter what's on this list.
NETWORK_PROGRAMS: Final[frozenset[str]] = frozenset(
    {
        "curl",
        "curl.exe",
        "wget",
        "wget.exe",
        "ncat",
        "ncat.exe",
        "netcat",
        "netcat.exe",
        "nc",
        "nc.exe",
        "ssh",
        "ssh.exe",
        "scp",
        "scp.exe",
        "sftp",
        "sftp.exe",
        "rsync",
        "rsync.exe",
        "ftp",
        "ftp.exe",
        "tftp",
        "tftp.exe",
        "telnet",
        "telnet.exe",
        "dig",
        "dig.exe",
        "nslookup",
        "nslookup.exe",
        "host",
        "host.exe",
        "whois",
        "whois.exe",
    }
)

# Upper sanity cap on any timeout the caller requests.
MAX_TIMEOUT_S: Final[int] = 600


# ---------------------------------------------------------------------------
# Block reasons — string constants used in RunResult.reason
# ---------------------------------------------------------------------------


class BlockReason:
    SHELL_STRING = "command must be list[str], not a shell string"
    NON_STRING_ARG = "every command argument must be a str"
    EMPTY_COMMAND = "command must be a non-empty list"
    SHELL_TRUE = "shell=True is forbidden by the hardened runner"
    BAD_TIMEOUT = "timeout must be a positive integer"
    BAD_WORKSPACE = "workspace must be an existing directory"
    CWD_OUTSIDE_WORKSPACE = "cwd resolves outside workspace"
    DOCKER_REFUSED = (
        "Docker/container runtime refused by default (pass allow_docker=True to opt in)"
    )
    NETWORK_REFUSED = (
        "network-enabling command refused by default (pass allow_network=True to opt in)"
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Structured outcome from :func:`run`. Never indicates success by
    exception — all failure modes are flags + a ``reason`` string."""

    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    tool_missing: bool = False
    blocked: bool = False
    reason: str = ""
    scrubbed_env_vars: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return (
            not self.blocked
            and not self.timed_out
            and not self.tool_missing
            and self.exit_code == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "command": list(self.command),
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "tool_missing": self.tool_missing,
            "blocked": self.blocked,
            "reason": self.reason,
            "scrubbed_env_vars": list(self.scrubbed_env_vars),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def scrub_env(extra_env: Mapping[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    """Return ``(scrubbed_env, stripped_keys)``.

    The base environment is ``os.environ`` minus every key in
    ``BLOCKED_ENV_VARS``. ``extra_env`` is then merged in, with the same
    blocklist applied — callers cannot smuggle a blocked var through the
    override.
    """
    stripped: list[str] = []
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        if k in BLOCKED_ENV_VARS:
            stripped.append(k)
            continue
        out[k] = v
    if extra_env:
        for k, v in extra_env.items():
            if k in BLOCKED_ENV_VARS:
                if k not in stripped:
                    stripped.append(k)
                continue
            out[k] = v
    return out, sorted(set(stripped))


def _is_inside(child: Path, parent: Path) -> bool:
    """True iff ``child`` resolves to a path inside ``parent`` (or equals
    it). Uses :py:meth:`pathlib.PurePath.is_relative_to` (Python 3.9+)."""
    try:
        return child.resolve(strict=False).is_relative_to(parent.resolve(strict=False))
    except (OSError, ValueError):
        return False


def _to_list_argv(cmd: object) -> list[str] | None:
    """Validate that cmd is a non-empty sequence of strings. Returns the
    list or None if invalid."""
    if isinstance(cmd, str):
        return None
    if not isinstance(cmd, (list, tuple)):
        return None
    out: list[str] = []
    for x in cmd:
        if not isinstance(x, str):
            return None
        out.append(x)
    return out


def _blocked(
    cmd: object,
    cwd: object,
    reason: str,
    scrubbed: list[str] | None = None,
) -> RunResult:
    if isinstance(cmd, (list, tuple)):
        cmd_list = [str(x) for x in cmd]
    else:
        cmd_list = [str(cmd)] if cmd is not None else []
    return RunResult(
        command=cmd_list,
        cwd=str(cwd) if cwd is not None else "",
        exit_code=-1,
        stdout="",
        stderr=reason,
        blocked=True,
        reason=reason,
        scrubbed_env_vars=list(scrubbed or []),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    cmd: Sequence[str],
    *,
    workspace: Path,
    timeout: int,
    extra_env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    allow_docker: bool = False,
    allow_network: bool = False,
    stdin: str | None = None,
    output_limit: int | None = 8000,
) -> RunResult:
    """Run ``cmd`` under the hardened runner.

    All failure modes are returned as structured fields on the
    ``RunResult``; this function never raises into the caller.

    :param cmd: must be a non-empty list/tuple of str. Shell strings are
        rejected.
    :param workspace: required directory; ``cwd`` MUST resolve inside it.
    :param timeout: positive int seconds. Clamped to MAX_TIMEOUT_S.
    :param extra_env: optional extra env vars merged after scrubbing.
        Blocked vars in ``extra_env`` are also stripped.
    :param cwd: optional sub-cwd inside workspace; defaults to workspace.
    :param allow_docker: opt-in to permit Docker / container runtimes.
        Claude lane never sets this.
    :param allow_network: opt-in to permit curl/wget/nc. Claude lane never
        sets this.
    :param stdin: optional text fed to the process stdin (decoded/encoded as
        UTF-8). ``None`` means no stdin. Lets oracles drive CLIs that read
        from stdin without bypassing the hardened envelope.
    :param output_limit: max chars kept from stdout/stderr (default 8000).
        Pass ``None`` to keep full output — required by output-comparison
        oracles that must match a program's complete stdout byte-for-byte.
    """
    # Validate command shape -------------------------------------------------
    cmd_list = _to_list_argv(cmd)
    if cmd_list is None:
        if isinstance(cmd, str):
            return _blocked(cmd, cwd or workspace, BlockReason.SHELL_STRING)
        return _blocked(cmd, cwd or workspace, BlockReason.NON_STRING_ARG)
    if not cmd_list:
        return _blocked(cmd, cwd or workspace, BlockReason.EMPTY_COMMAND)

    # Validate timeout -------------------------------------------------------
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        return _blocked(cmd_list, cwd or workspace, BlockReason.BAD_TIMEOUT)
    effective_timeout = min(timeout, MAX_TIMEOUT_S)

    # Validate workspace -----------------------------------------------------
    if not isinstance(workspace, Path):
        return _blocked(cmd_list, cwd, BlockReason.BAD_WORKSPACE)
    ws_resolved = workspace.resolve(strict=False)
    if not ws_resolved.is_dir():
        return _blocked(
            cmd_list,
            cwd or workspace,
            f"{BlockReason.BAD_WORKSPACE}: {ws_resolved}",
        )

    # Validate cwd -----------------------------------------------------------
    use_cwd = (cwd if cwd is not None else workspace).resolve(strict=False)
    if not _is_inside(use_cwd, ws_resolved):
        return _blocked(cmd_list, use_cwd, BlockReason.CWD_OUTSIDE_WORKSPACE)

    # Refuse Docker / network --------------------------------------------------
    program = Path(cmd_list[0]).name.lower()
    if not allow_docker and program in REFUSED_PROGRAMS:
        return _blocked(cmd_list, use_cwd, BlockReason.DOCKER_REFUSED)
    if not allow_network and program in NETWORK_PROGRAMS:
        return _blocked(cmd_list, use_cwd, BlockReason.NETWORK_REFUSED)

    # Scrub env --------------------------------------------------------------
    env, stripped = scrub_env(extra_env)

    # Execute (shell=False is explicit; subprocess.run never raises here
    # because we catch every documented exception) -------------------------
    # shutil.which resolves Windows' .cmd/.bat shims (PATHEXT) -- a bare
    # subprocess.run(shell=False) does NOT try these extensions the way a
    # real shell (or Rust's std::process::Command) does, so an npm-installed
    # tool like "npx" (a .cmd wrapper, not a .exe) raised a raw
    # FileNotFoundError here. Found live 2026-07-22: this is the SAME
    # Windows PATHEXT bug already fixed twice this session for spawning
    # claude-code/codex/gemini-cli (determinex_agents.py's resolve_argv) --
    # this is the third, independent place it existed, silently making
    # _verify_typescript's tsc/jest checks fail to launch and (before that
    # bug was also fixed) get reported as a false PASS. Only argv[0] is
    # resolved; the rest of cmd_list is real argument text, and shell=False
    # stays exactly as it was (never shell=True -- this is a security
    # boundary, not something this fix touches).
    resolved_cmd = [shutil.which(cmd_list[0]) or cmd_list[0], *cmd_list[1:]]
    try:
        proc = subprocess.run(
            resolved_cmd,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(use_cwd),
            timeout=effective_timeout,
            env=env,
            shell=False,
            check=False,
        )
        _clip = (lambda s: s) if output_limit is None else (lambda s: s[:output_limit])
        return RunResult(
            command=cmd_list,
            cwd=str(use_cwd),
            exit_code=proc.returncode,
            stdout=_clip(proc.stdout or ""),
            stderr=_clip(proc.stderr or ""),
            scrubbed_env_vars=stripped,
        )
    except FileNotFoundError as e:
        return RunResult(
            command=cmd_list,
            cwd=str(use_cwd),
            exit_code=-2,
            stdout="",
            stderr=f"tool not found on PATH: {cmd_list[0]} ({e})",
            tool_missing=True,
            reason=f"tool not found: {cmd_list[0]}",
            scrubbed_env_vars=stripped,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            command=cmd_list,
            cwd=str(use_cwd),
            exit_code=-3,
            stdout="",
            stderr=f"timed out after {effective_timeout}s",
            timed_out=True,
            reason=f"timed out after {effective_timeout}s",
            scrubbed_env_vars=stripped,
        )
    except PermissionError as e:
        return RunResult(
            command=cmd_list,
            cwd=str(use_cwd),
            exit_code=-4,
            stdout="",
            stderr=f"permission denied: {e}",
            reason=f"permission denied: {e}",
            scrubbed_env_vars=stripped,
        )
    except OSError as e:
        # Catch anything else subprocess can raise (e.g. WinError 5).
        return RunResult(
            command=cmd_list,
            cwd=str(use_cwd),
            exit_code=-5,
            stdout="",
            stderr=f"OS error invoking {cmd_list[0]}: {e}",
            reason=f"OS error: {e}",
            scrubbed_env_vars=stripped,
        )
