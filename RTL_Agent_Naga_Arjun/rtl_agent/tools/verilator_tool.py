"""
verilator_tool.py -- Subprocess wrapper for the Verilator lint tool.

Flag rationale (Verilator 5.x -- verilator.org/guide "Arguments"):
  -Wall          Enables all lint warnings, promoting them to errors.
  -Wno-style     Suppresses DECLFILENAME, EOFNEWLINE, UNUSEDSIGNAL, UNDRIVEN, etc.
                 The agent names files {session_id}_iter{N}.sv; module names differ
                 (e.g. "mux2to1") -- guaranteed DECLFILENAME on every run without this.
  -Wno-fatal     Prevents non-fatal warnings from setting a non-zero exit code.
                 Without this, style warnings that slip through (WIDTHTRUNC, etc.)
                 would cause the agent to enter a correction loop for cosmetic issues.
                 The warning text is still captured in stderr for LLM context.
  --timing       Required for timing annotations in SV.
  WIDTH kept:    Bit-width mismatches are genuine bugs. Do NOT add -Wno-WIDTH.

success determination:
  We use  "%Error" not in combined_output  rather than  returncode == 0.
  Verilator can exit 1 even when only warnings are present (before -Wno-fatal
  is fully effective on all versions). String-based detection is more reliable.
"""

import subprocess
import sys
from pathlib import Path


def run_verilator(filepath: str, timeout: int = 30) -> dict:
    """
    Execute Verilator lint check on a SystemVerilog file.

    Returns dict with keys: success, stdout, stderr, returncode.
    success is determined by "%Error" NOT in combined output (not returncode).
    """
    sv_path = Path(filepath).resolve()

    # Each flag is its own list element -- no spaces inside items.
    _flags = [
        "--lint-only",
        "-Wall",        # canonical single-dash form per verilator.org/guide
        "-Wno-style",   # suppress DECLFILENAME, EOFNEWLINE, UNUSEDSIGNAL, etc.
        "-Wno-fatal",   # non-fatal warnings do not set exit code 1
        "--timing",
    ]

    if sys.platform == "win32":
        posix_path = "/mnt/" + str(sv_path).replace("\\", "/").replace(":", "", 1).lower()
        cmd = ["wsl", "verilator"] + _flags + [posix_path]
    else:
        cmd = ["verilator"] + _flags + [str(sv_path)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Log to disk for debugging (helps investigate unexpected lint failures)
        try:
            log_path = str(sv_path).replace(".sv", "_verilator.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"EXIT CODE: {result.returncode}\n")
                f.write("=== STDOUT ===\n")
                f.write(result.stdout or "No standard output.\n")
                f.write("\n=== STDERR ===\n")
                f.write(result.stderr or "No standard error.\n")
        except Exception:
            pass  # never crash the lint check due to a debug log write

        combined_output = (result.stdout or "") + (result.stderr or "")
        is_success = "%Error" not in combined_output

        return {
            "success":    is_success,
            "stdout":     result.stdout,
            "stderr":     result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     (
                f"[RTL-AGENT ERROR] Verilator timed out after {timeout} seconds.\n"
                "The design may contain a very large hierarchy or an infinite loop construct."
            ),
            "returncode": -1,
        }

    except FileNotFoundError:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     (
                "[RTL-AGENT ERROR] Verilator executable not found.\n"
                "Install with: sudo apt-get install verilator"
            ),
            "returncode": -2,
        }

    except Exception as exc:
        return {
            "success":    False,
            "stdout":     "",
            "stderr":     f"[RTL-AGENT ERROR] Unexpected error running verilator: {exc}",
            "returncode": -3,
        }


def filter_verilator_errors(raw_output: str) -> str:
    """
    Extract only %Error / %Warning lines + source-location context.
    Strips URL hints and lint_off suggestions -- even when they appear as
    indented continuation lines after a diagnostic.

    Passes only the relevant lines to the LLM correction prompt.
    A 7B model has limited long-context attention; sending a 60-line log when
    only 3 lines are relevant degrades correction accuracy significantly.

    Returns filtered string; falls back to raw_output if nothing found.
    """
    _NOISE = ("For warning description see", 'Use "/* verilator lint_off')

    lines = (raw_output or "").splitlines()
    keep, capturing = [], False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("%Error") or stripped.startswith("%Warning"):
            if any(n in stripped for n in _NOISE):
                capturing = False
                continue
            capturing = True
            keep.append(line)

        elif capturing:
            # Skip noise continuation lines even when indented
            if any(n in stripped for n in _NOISE):
                capturing = False
                continue
            # Keep genuine continuations: source line, caret, note lines
            if line.startswith((" ", "\t")) or stripped.startswith(("...", "|", "^")):
                keep.append(line)
            else:
                capturing = False

    if not keep:
        return raw_output

    error_count   = sum(1 for l in keep if l.strip().startswith("%Error"))
    warning_count = sum(1 for l in keep if l.strip().startswith("%Warning"))
    return (
        f"[Verilator: {error_count} error(s), {warning_count} warning(s)]\n"
        + "\n".join(keep)
    )
