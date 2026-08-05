"""Module 2 — Divergence capture.

Runs the candidate binary under a scripted debugger (gdb MI for C/C++/Rust,
delve for Go) against the failing test input, captures the abort/exit/panic
path, and returns a compact divergence section.

Only the CANDIDATE is debugged.  Reference stays black-box.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import DiagnosticSection

logger = logging.getLogger(__name__)

_DEBUGGER_TIMEOUT = 60.0

_GDB_SCRIPT_TEMPLATE = """\
set pagination off
set confirm off
set width 200
run {args}
bt 10
info locals
quit
"""

_DELVE_SCRIPT_TEMPLATE = """\
continue
goroutine all bt
quit
"""

_DEBUGGABLE_LANGS = {"rust", "c", "cpp", "go"}


def _gdb_available() -> bool:
    return shutil.which("gdb") is not None


def _delve_available() -> bool:
    return shutil.which("dlv") is not None


async def _run_gdb(
    candidate: Path,
    test_args: list[str],
    stdin_data: bytes | None,
    timeout: float,
) -> dict[str, Any]:
    """Run candidate under gdb MI and return structured output."""
    if not _gdb_available():
        return {"error": "gdb not found"}

    args_str = " ".join(f'"{a}"' for a in test_args)
    script = _GDB_SCRIPT_TEMPLATE.format(args=args_str)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".gdb", delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        cmd = ["gdb", "--batch", "-x", script_path, "--args", str(candidate)] + test_args
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            return {"error": "gdb timeout"}

        output = (stdout + stderr).decode("utf-8", errors="replace")
        # Extract stack and locals
        stack_lines = [
            line for line in output.splitlines() if line.startswith("#") or "at " in line
        ][:10]
        local_lines = [
            line for line in output.splitlines() if " = " in line and not line.startswith("#")
        ][:5]
        return {
            "stack": "\n".join(stack_lines),
            "locals_excerpt": "\n".join(local_lines),
            "exit_code": proc.returncode,
        }
    finally:
        os.unlink(script_path)


async def _run_delve(
    candidate: Path,
    test_args: list[str],
    stdin_data: bytes | None,
    timeout: float,
) -> dict[str, Any]:
    """Run candidate under delve and return structured output."""
    if not _delve_available():
        return {"error": "dlv not found"}

    cmd = ["dlv", "exec", str(candidate), "--headless=false", "--"] + test_args
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        # Send delve commands
        delve_input = _DELVE_SCRIPT_TEMPLATE.encode("utf-8")
        if stdin_data:
            delve_input = stdin_data + b"\n" + delve_input
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=delve_input), timeout=timeout
        )
    except TimeoutError:
        proc.kill()
        return {"error": "dlv timeout"}

    output = (stdout + stderr).decode("utf-8", errors="replace")
    stack_lines = [
        line for line in output.splitlines() if "goroutine" in line or line.strip().startswith("*")
    ][:10]
    return {
        "stack": "\n".join(stack_lines),
        "locals_excerpt": "",
        "exit_code": proc.returncode,
    }


async def capture_divergence(
    candidate: Path,
    lang: str,
    test_id: str,
    test_args: list[str],
    stdin_data: bytes | None = None,
    timeout: float = _DEBUGGER_TIMEOUT,
) -> DiagnosticSection:
    """Run candidate under debugger, return divergence section.

    On Windows or when the debugger is unavailable, returns an empty section
    with a WAL note — never raises.
    """
    if lang not in _DEBUGGABLE_LANGS:
        return DiagnosticSection(kind="divergence", rank=2, content=[])

    # Windows: gdb/delve exist but job-object isolation may interfere.
    # Skip gracefully; Hetzner (Linux) is the primary platform for debugging.
    if sys.platform == "win32":
        return DiagnosticSection(
            kind="divergence",
            rank=2,
            content=[{"test_id": test_id, "divergence_point": "windows_skip", "stack": ""}],
        )

    result: dict[str, Any]
    try:
        if lang == "go":
            result = await _run_delve(candidate, test_args, stdin_data, timeout)
        else:
            result = await _run_gdb(candidate, test_args, stdin_data, timeout)
    except Exception as exc:
        logger.warning("Divergence capture error: %s", exc)
        result = {"error": str(exc)}

    item = {
        "test_id": test_id,
        "divergence_point": result.get("error", "captured"),
        "stack": result.get("stack", ""),
        "locals_excerpt": result.get("locals_excerpt", ""),
        "exit_code": result.get("exit_code"),
    }
    return DiagnosticSection(
        kind="divergence",
        rank=2,
        content=[item],
        token_estimate=len(str(item)) // 4,
    )
