"""
validators/rust_validator.py - Rust Code Compilation Validator

Writes the generated Rust code to a temp file and calls rustc to compile it.
Pass = rustc exits 0 (no errors). Fail = any compile error in stderr.

Requires: rustc on PATH (standard Rust installation).
Windows-compatible: uses .rs/.exe temp files with proper cleanup.
"""

import logging
import os
import re
import subprocess
import tempfile

log = logging.getLogger("oracle.validator.rust")

# Timeout for rustc compilation (seconds)
COMPILE_TIMEOUT = 30


def _strip_markdown_fences(code: str) -> str:
    """Remove ```rust ... ``` or ``` ... ``` fences if the model included them."""
    code = code.strip()
    # Strip opening fence with optional language tag
    code = re.sub(r"^```(?:rust)?\s*\n", "", code, flags=re.MULTILINE)
    # Strip closing fence
    code = re.sub(r"\n```\s*$", "", code, flags=re.MULTILINE)
    return code.strip()


def _wrap_in_harness(code: str) -> str:
    """
    Wrap free-floating functions/structs in a minimal Rust lib harness so rustc
    can compile them without a main() entry point.

    If the code already contains 'fn main' or '#![...] extern crate', leave as-is.
    """
    if "fn main" in code:
        return code

    # Inject common crate-level allows to suppress pedantic warnings that
    # would obscure real errors, plus common imports the teacher might assume.
    preamble = (
        "#![allow(dead_code, unused_variables, unused_imports)]\n"
        "use std::collections::HashMap;\n"
        "use std::path::Path;\n"
        "use std::fs;\n"
        "use std::io;\n"
    )
    return preamble + "\n" + code


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Compile Rust code with rustc. Returns (passed, reason).

    Args:
        output:    Raw text from the teacher model.
        task_meta: Curriculum task dict (unused, but part of the standard interface).

    Returns:
        (True, "Compiled successfully") on pass.
        (False, "rustc error: <stderr excerpt>") on fail.
    """
    code = _strip_markdown_fences(output)

    if len(code) < 10:
        return False, "Output too short to be valid Rust code"

    wrapped = _wrap_in_harness(code)

    # Write to a temp .rs file — use suffix so rustc recognises the extension
    with tempfile.NamedTemporaryFile(suffix=".rs", delete=False, mode="w", encoding="utf-8") as tmp:
        tmp.write(wrapped)
        src_path = tmp.name

    # rustc writes the binary next to the source; we don't need it
    out_path = src_path.replace(".rs", ".out")

    try:
        result = subprocess.run(
            [
                "rustc",
                "--edition",
                "2021",
                "--crate-type",
                "lib",  # no main() required
                "-o",
                out_path,
                src_path,
            ],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )

        if result.returncode == 0:
            log.debug("rustc PASS for %d chars of code", len(code))
            return True, "Compiled successfully"

        # Extract first meaningful error line from stderr
        stderr_lines = [
            ln for ln in result.stderr.splitlines() if ln.strip() and not ln.startswith("   =")
        ]
        first_error = "\n".join(stderr_lines[:5]) if stderr_lines else result.stderr[:300]
        log.debug("rustc FAIL: %s", first_error[:200])
        return False, f"rustc error:\n{first_error[:400]}"

    except FileNotFoundError:
        log.error("rustc not found on PATH -- is Rust installed?")
        return False, "rustc not found on PATH"
    except subprocess.TimeoutExpired:
        log.warning("rustc compilation timed out after %ds", COMPILE_TIMEOUT)
        return False, f"Compilation timed out after {COMPILE_TIMEOUT}s"
    except Exception as e:
        log.error("Rust validator unexpected error: %s", e)
        return False, f"Validator error: {e}"
    finally:
        # Clean up temp files regardless of outcome
        for path in (src_path, out_path):
            try:
                os.unlink(path)
            except OSError:
                pass
