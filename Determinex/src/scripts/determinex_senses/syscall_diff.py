"""Module 3 — Syscall differential.

BRIGHT LINE — enforced in code and docs:
  Dynamic observation ONLY: run, trace, fuzz.
  NO objdump / disassembly / decompilation / symbol-dumping of the reference binary.
  Any invocation of static-RE tools (objdump, readelf, radare2, ghidra, ida, etc.)
  against a reference executable is REFUSED and logged.

Linux/Hetzner only.  On Windows, returns an empty section with a WAL note.

Algorithm:
  1. Run REFERENCE under strace -f -e trace=file,desc,process
  2. Run CANDIDATE identically
  3. Normalize traces (strip pids, addrs, tmp paths) and diff
  4. Emit: first divergent syscall, file-access-order deltas, exit-path diffs
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import DiagnosticSection

logger = logging.getLogger(__name__)

_STRACE_TIMEOUT = 60.0

# Static reverse-engineering tools that MUST NOT be called against reference binaries.
_STATIC_RE_TOOLS = frozenset(
    {
        "objdump",
        "readelf",
        "nm",
        "strings",
        "radare2",
        "r2",
        "ghidra",
        "ida",
        "ida64",
        "iaito",
        "binaryninja",
        "binary_ninja",
        "rizin",
        "rz-bin",
        "capstone",
        "unicorn",
        "angr",
        "pwntool",
        "pwndbg",
        "peda",
    }
)


def refuse_static_re(tool_name: str) -> None:
    """Raise if tool_name is a static-RE tool.  Call before any subprocess exec."""
    normalized = tool_name.lower()
    if normalized.endswith(".exe"):
        normalized = normalized[:-4]
    if normalized in _STATIC_RE_TOOLS:
        msg = (
            f"SENSES BRIGHT LINE: static reverse-engineering tool '{tool_name}' "
            "must not be used against reference binaries. Refusing."
        )
        logger.error(msg)
        raise ValueError(msg)


def _normalize_trace_line(line: str) -> str:
    """Strip pid prefix, addresses, and temp paths for comparison."""
    # Strip leading "[pid NNNNN]" or bare "NNNNN " PID prefixes
    line = re.sub(r"^\[pid\s+\d+\]\s*", "", line)
    line = re.sub(r"^\d+\s+", "", line)
    # Strip memory addresses 0x...
    line = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", line)
    # Strip temp paths /tmp/... or /var/tmp/...
    line = re.sub(r"(/(?:tmp|var/tmp)/[^\s\",)]+)", "/TMPPATH", line)
    # Strip numeric fd values in some calls
    line = re.sub(r"\bfd=\d+\b", "fd=N", line)
    return line.strip()


async def _run_strace(
    binary: Path,
    args: list[str],
    stdin_data: bytes | None,
    timeout: float,
) -> list[str]:
    """Run binary under strace, return normalized trace lines."""
    with tempfile.NamedTemporaryFile(suffix=".strace", delete=False) as tf:
        trace_path = tf.name

    cmd = [
        "strace",
        "-f",
        "-e",
        "trace=file,desc,process",
        "-o",
        trace_path,
        str(binary),
    ] + args

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(
            proc.communicate(input=stdin_data),
            timeout=timeout,
        )
    except TimeoutError:
        proc.kill()

    try:
        raw = Path(trace_path).read_text(encoding="utf-8", errors="replace")
        Path(trace_path).unlink(missing_ok=True)
    except OSError:
        return []

    return [_normalize_trace_line(line) for line in raw.splitlines() if line.strip()]


def _diff_traces(ref_lines: list[str], cand_lines: list[str]) -> dict[str, Any]:
    """Find the first divergence between two normalized strace outputs."""
    # Compare line by line up to the shorter length
    first_diff: str | None = None
    for i, (r, c) in enumerate(zip(ref_lines, cand_lines)):
        if r != c:
            first_diff = f"line {i}: ref={r!r:.100} | cand={c!r:.100}"
            break

    if first_diff is None and len(ref_lines) != len(cand_lines):
        diff_len = abs(len(ref_lines) - len(cand_lines))
        first_diff = (
            f"length divergence: ref={len(ref_lines)} cand={len(cand_lines)} (delta={diff_len})"
        )

    # File-access order: extract openat/open calls
    ref_opens = [ln for ln in ref_lines if "openat(" in ln or "open(" in ln]
    cand_opens = [ln for ln in cand_lines if "openat(" in ln or "open(" in ln]
    file_delta: list[str] = []
    for i, (r, c) in enumerate(zip(ref_opens, cand_opens)):
        if r != c:
            file_delta.append(f"open#{i}: ref={r!r:.80} cand={c!r:.80}")
            if len(file_delta) >= 5:
                break

    # Exit path: last 10 lines
    ref_tail = ref_lines[-10:]
    cand_tail = cand_lines[-10:]
    exit_diff = ref_tail != cand_tail

    return {
        "first_diff": first_diff or "no_divergence",
        "file_access_delta": file_delta,
        "exit_path_differs": exit_diff,
        "ref_syscall_count": len(ref_lines),
        "cand_syscall_count": len(cand_lines),
        "summary": (
            f"{len(file_delta)} file-order deltas; exit differs={exit_diff}"
            if first_diff
            else "identical traces"
        ),
    }


async def run_syscall_diff(
    reference: Path,
    candidate: Path,
    test_args: list[str],
    stdin_data: bytes | None = None,
    timeout: float = _STRACE_TIMEOUT,
) -> DiagnosticSection:
    """Run reference and candidate under strace, diff, return section.

    Linux only — returns empty section on Windows with WAL note.
    The reference binary is run with strace ONLY (dynamic observation).
    No static analysis is performed.
    """
    # Refuse static-RE tools (defensive check on binary names)
    for b in [reference, candidate]:
        refuse_static_re(b.stem)

    if sys.platform == "win32":
        return DiagnosticSection(
            kind="syscall_diff",
            rank=3,
            content=[{"first_diff": "windows_skip", "summary": "strace not available on Windows"}],
        )

    try:
        import shutil

        if not shutil.which("strace"):
            return DiagnosticSection(
                kind="syscall_diff",
                rank=3,
                content=[
                    {"first_diff": "strace_not_found", "summary": "strace binary not in PATH"}
                ],
            )
    except Exception:
        pass

    ref_lines: list[str] = []
    cand_lines: list[str] = []

    try:
        ref_lines = await _run_strace(reference, test_args, stdin_data, timeout / 2)
    except Exception as exc:
        logger.warning("strace on reference failed: %s", exc)

    try:
        cand_lines = await _run_strace(candidate, test_args, stdin_data, timeout / 2)
    except Exception as exc:
        logger.warning("strace on candidate failed: %s", exc)

    if not ref_lines and not cand_lines:
        return DiagnosticSection(
            kind="syscall_diff",
            rank=3,
            content=[{"first_diff": "strace_empty", "summary": "no trace output captured"}],
        )

    diff = _diff_traces(ref_lines, cand_lines)
    return DiagnosticSection(
        kind="syscall_diff",
        rank=3,
        content=[diff],
        token_estimate=len(str(diff)) // 4,
    )
