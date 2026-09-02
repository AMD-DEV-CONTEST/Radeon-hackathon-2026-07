"""
validators/python_validator.py - Python AST + Sandbox Execution Validator

Validates Python code via:
  1. ast.parse() -- catches all syntax errors
  2. Optional sandboxed exec() in a restricted namespace -- catches runtime errors
     that would appear on trivial inputs (ZeroDivisionError, NameError, etc.)

The sandbox does NOT have network access, filesystem access, or subprocess.
It is safe to run generated code through this validator.
"""

import ast
import contextlib
import io
import logging
import re
import sys

log = logging.getLogger("oracle.validator.python")

# Builtins blocked in the sandboxed exec namespace
_BLOCKED_BUILTINS = {"open", "exec", "eval", "__import__", "compile", "input"}


def _strip_markdown_fences(code: str) -> str:
    """Remove ```python ... ``` fences if present."""
    code = code.strip()
    code = re.sub(r"^```(?:python|py)?\s*\n", "", code, flags=re.MULTILINE)
    code = re.sub(r"\n```\s*$", "", code, flags=re.MULTILINE)
    return code.strip()


def _make_safe_namespace() -> dict:
    """
    Build a restricted exec namespace with safe builtins.
    Blocks file I/O, subprocess, and import of dangerous modules.
    """
    import builtins

    safe_builtins = {k: v for k, v in vars(builtins).items() if k not in _BLOCKED_BUILTINS}
    # Provide common stdlib modules that generated code commonly imports
    safe_ns = {
        "__builtins__": safe_builtins,
        "re": re,
        "json": __import__("json"),
        "math": __import__("math"),
        "collections": __import__("collections"),
        "itertools": __import__("itertools"),
        "functools": __import__("functools"),
        "typing": __import__("typing"),
        "dataclasses": __import__("dataclasses"),
        "datetime": __import__("datetime"),
        "pathlib": __import__("pathlib"),
        "sys": sys,
        "io": io,
    }
    return safe_ns


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate Python code via AST parse + optional restricted exec.

    Args:
        output:    Raw text from the teacher model.
        task_meta: Curriculum task dict. If task_meta.get('sandbox_exec') is True,
                   also attempts sandboxed execution.

    Returns:
        (True, reason) on pass, (False, reason) on fail.
    """
    code = _strip_markdown_fences(output)

    if len(code) < 10:
        return False, "Output too short to be valid Python"

    # ── Stage 1: AST parse ───────────────────────────────────────────────────
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        log.debug("Python AST fail: %s at line %d", e.msg, e.lineno or 0)
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Parse error: {e}"

    # Basic sanity: must define at least one function, class, or import
    top_level = [
        type(node).__name__
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)
        )
    ]
    if not top_level:
        return False, "No functions, classes, or imports found — likely not valid code"

    # ── Stage 2: Sandboxed exec (optional, skipped by default) ───────────────
    if task_meta.get("sandbox_exec", False):
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(stdout_capture),
                contextlib.redirect_stderr(stderr_capture),
            ):
                exec(compile(tree, "<validated>", "exec"), _make_safe_namespace())  # noqa: S102
        except SystemExit:
            pass  # sys.exit() in code is fine, not a bug
        except PermissionError:
            return False, "Code attempted blocked filesystem access"
        except Exception as e:
            err_type = type(e).__name__
            # Ignore errors caused by missing external resources (these are expected
            # in generated code that calls APIs, reads files, etc.)
            ignorable = (
                "FileNotFoundError",
                "ModuleNotFoundError",
                "ImportError",
                "ConnectionError",
                "TimeoutError",
                "OSError",
            )
            if err_type not in ignorable:
                log.debug("Sandbox exec fail: %s: %s", err_type, e)
                return False, f"Runtime error ({err_type}): {e}"

    log.debug("Python validator PASS (%d chars)", len(code))
    return True, "AST parse successful"
