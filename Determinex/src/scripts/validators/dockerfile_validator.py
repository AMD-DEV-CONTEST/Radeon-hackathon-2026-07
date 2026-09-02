"""
validators/dockerfile_validator.py — Dockerfile parse + hadolint
==================================================================
Validates Dockerfile output in two stages:
  1. Manual directive parse — every non-comment, non-blank line must start with
     a known Dockerfile instruction or a line-continuation from the previous one.
  2. hadolint JSON output if installed — DL3xxx errors fail; warnings allowed.

We deliberately do NOT shell out to `docker build` because that would pull base
images and write to the daemon — too heavy for a training-gate validator. The
manual parse is conservative; hadolint is the semantic backbone when available.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

log = logging.getLogger("oracle.validator.dockerfile")

_FENCE_RE = re.compile(r"^```(?:dockerfile|docker)?\s*\n|\n```\s*$", flags=re.MULTILINE)

_DOCKERFILE_INSTRUCTIONS = frozenset(
    {
        "FROM",
        "RUN",
        "CMD",
        "LABEL",
        "MAINTAINER",
        "EXPOSE",
        "ENV",
        "ADD",
        "COPY",
        "ENTRYPOINT",
        "VOLUME",
        "USER",
        "WORKDIR",
        "ARG",
        "ONBUILD",
        "STOPSIGNAL",
        "HEALTHCHECK",
        "SHELL",
    }
)

_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def _strip_markdown_fences(code: str) -> str:
    return _FENCE_RE.sub("", code.strip()).strip()


def _manual_parse(text: str) -> tuple[bool, str]:
    in_continuation = False
    in_heredoc: str | None = None
    saw_from = False
    line_no = 0
    for raw_line in text.splitlines():
        line_no += 1
        line = raw_line.rstrip()
        # heredoc handling — opaque to instruction matching
        if in_heredoc:
            if line.strip() == in_heredoc:
                in_heredoc = None
            continue
        # skip blanks and comments
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            in_continuation = line.endswith("\\")
            continue
        # continuation lines are inside a previous instruction
        if in_continuation:
            heredoc = _HEREDOC_RE.search(line)
            if heredoc:
                in_heredoc = heredoc.group(1)
            in_continuation = line.endswith("\\")
            continue
        # first token must be a known instruction (case-insensitive but conventionally upper)
        first = stripped.split(None, 1)[0]
        upper = first.upper()
        if upper not in _DOCKERFILE_INSTRUCTIONS:
            return False, f"L{line_no}: unknown Dockerfile instruction '{first}'"
        if upper == "FROM":
            saw_from = True
        heredoc = _HEREDOC_RE.search(line)
        if heredoc:
            in_heredoc = heredoc.group(1)
        in_continuation = line.endswith("\\")
    if not saw_from:
        return False, "Dockerfile must contain at least one FROM instruction"
    return True, "manual directive parse passed"


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate a Dockerfile.

    task_meta keys:
        hadolint_strict (bool):  any hadolint warning fails (default: only errors fail).
        skip_hadolint (bool):    skip hadolint even if installed.
    """
    code = _strip_markdown_fences(output)
    if len(code) < 5:
        return False, "Output too short to be a valid Dockerfile"

    ok, reason = _manual_parse(code)
    if not ok:
        return False, reason

    if task_meta.get("skip_hadolint"):
        return True, reason

    hadolint = shutil.which("hadolint") or shutil.which("hadolint.exe")
    if not hadolint:
        return True, f"{reason}; hadolint unavailable"

    with tempfile.NamedTemporaryFile(
        "w", suffix=".dockerfile", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(code)
        path = fh.name
    try:
        result = subprocess.run(
            [hadolint, "--format", "json", path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True, f"{reason}; hadolint clean"
        try:
            findings = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            findings = []
        errors = [f for f in findings if f.get("level") == "error"]
        warnings = [f for f in findings if f.get("level") == "warning"]
        if errors:
            first = errors[0]
            return (
                False,
                f"hadolint {first.get('code')}: {first.get('message')} @ L{first.get('line')}",
            )
        if task_meta.get("hadolint_strict") and warnings:
            first = warnings[0]
            return False, f"hadolint strict {first.get('code')}: {first.get('message')}"
        return True, f"{reason}; {len(warnings)} hadolint warnings"
    except subprocess.TimeoutExpired:
        return False, "hadolint timeout"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
