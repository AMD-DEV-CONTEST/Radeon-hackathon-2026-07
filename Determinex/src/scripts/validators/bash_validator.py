"""
validators/bash_validator.py — Bash syntax + semantic validator
================================================================
Two-stage:
  1. `bash -n script.sh` for parse-correctness (always available on dev boxes).
  2. `shellcheck --format=json1 script.sh` for semantic warnings, when installed.

Treats shellcheck errors of level 'error' as failures; 'warning' and 'info'
are surfaced in the reason string but do NOT fail the sample (training data
should be permissive enough to teach the model patterns shellcheck flags).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

log = logging.getLogger("oracle.validator.bash")

_FENCE_RE = re.compile(r"^```(?:bash|sh|shell)?\s*\n|\n```\s*$", flags=re.MULTILINE)


def _strip_markdown_fences(code: str) -> str:
    return _FENCE_RE.sub("", code.strip()).strip()


def _bash_executable() -> str | None:
    return shutil.which("bash") or shutil.which("bash.exe")


def _shellcheck_executable() -> str | None:
    return shutil.which("shellcheck") or shutil.which("shellcheck.exe")


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate a Bash script. Returns (passed, reason).

    task_meta keys consulted:
        shellcheck_strict (bool): if True, warning-level shellcheck findings also fail.
        skip_shellcheck (bool):   if True, run only `bash -n`.
    """
    code = _strip_markdown_fences(output)
    if len(code) < 5:
        return False, "Output too short to be a valid Bash script"

    bash = _bash_executable()
    if not bash:
        return False, "bash not on PATH — cannot validate"

    # Stage 1 — bash -n syntax check
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as fh:
        fh.write(code)
        script_path = fh.name
    try:
        result = subprocess.run(
            [bash, "-n", script_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            err = (result.stderr or "").strip().splitlines()
            first = err[0] if err else "unknown syntax error"
            return False, f"bash -n failed: {first}"

        # Stage 2 — shellcheck semantic pass (optional)
        if task_meta.get("skip_shellcheck"):
            return True, "bash -n passed (shellcheck skipped)"

        sc = _shellcheck_executable()
        if not sc:
            return True, "bash -n passed (shellcheck unavailable)"

        strict = bool(task_meta.get("shellcheck_strict", False))
        sc_result = subprocess.run(
            [sc, "--format=json1", "--severity=warning", script_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if sc_result.returncode == 0:
            return True, "bash -n + shellcheck clean"

        try:
            payload = json.loads(sc_result.stdout or "{}")
            comments = payload.get("comments", []) if isinstance(payload, dict) else []
        except json.JSONDecodeError:
            comments = []

        errors = [c for c in comments if c.get("level") == "error"]
        warnings = [c for c in comments if c.get("level") == "warning"]
        if errors:
            first = errors[0]
            return False, (
                f"shellcheck SC{first.get('code')}: {first.get('message')} "
                f"@ line {first.get('line')}"
            )
        if strict and warnings:
            first = warnings[0]
            return False, (
                f"shellcheck strict SC{first.get('code')}: {first.get('message')} "
                f"@ line {first.get('line')}"
            )
        return True, f"bash -n passed; shellcheck warnings: {len(warnings)}"
    except subprocess.TimeoutExpired:
        return False, "validator timeout"
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
