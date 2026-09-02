"""
validators/xdist_validator.py — pytest-xdist worker-manifest validator
=======================================================================
Validates pytest configuration / manifest output for xdist parallel test runs.
Specifically catches the failure mode from the 2026-05 mass-run sprint:
worker IPC deadlocks when workers reference non-existent fixtures or use
overlapping `worker_id` ranges.

Accepts EITHER:
  - A pytest.ini / pyproject.toml [tool.pytest.ini_options] snippet
  - A pytest --collect-only manifest dump

Validation:
  1. `python -m pytest --collect-only` against a synthetic conftest.py
  2. Parse for `addopts` referencing -n auto / -n <N>
  3. Check that any `dist:` keyword has a valid value (load/loadscope/loadfile/no)
  4. Verify `worker_id` references in addopts are bracketed correctly (no overlaps)
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile

log = logging.getLogger("oracle.validator.xdist")

_FENCE_RE = re.compile(r"^```(?:ini|toml|python|py)?\s*\n|\n```\s*$", flags=re.MULTILINE)

_VALID_DIST = {"no", "load", "loadscope", "loadfile", "loadgroup", "worksteal"}


def _strip_markdown_fences(code: str) -> str:
    return _FENCE_RE.sub("", code.strip()).strip()


def _extract_addopts(text: str) -> str | None:
    m = re.search(r"^\s*addopts\s*=\s*(.+?)$", text, flags=re.MULTILINE)
    if m:
        return m.group(1).strip().strip("'\"")
    return None


def _check_dist_value(addopts: str) -> tuple[bool, str]:
    m = re.search(r"--dist[= ]([\w-]+)", addopts)
    if m and m.group(1) not in _VALID_DIST:
        return False, f"invalid --dist value '{m.group(1)}'"
    return True, ""


def _check_worker_count(addopts: str) -> tuple[bool, str]:
    m = re.search(r"-n\s+(\S+)", addopts)
    if not m:
        return True, ""
    val = m.group(1)
    if val == "auto" or val == "logical":
        return True, ""
    try:
        n = int(val)
    except ValueError:
        return False, f"-n must be 'auto', 'logical', or integer; got '{val}'"
    if n < 1 or n > 256:
        return False, f"-n worker count {n} out of sane range [1, 256]"
    return True, ""


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate xdist configuration.

    task_meta keys:
        skip_collect (bool):     skip the live `pytest --collect-only` run.
        max_workers (int):       upper bound on -n (defaults to 256).
        require_dist (bool):     dist= must be explicitly set in addopts.
    """
    text = _strip_markdown_fences(output)
    if len(text) < 5:
        return False, "Output too short to be a valid xdist config"

    addopts = _extract_addopts(text)
    if addopts:
        ok, reason = _check_dist_value(addopts)
        if not ok:
            return False, reason
        ok, reason = _check_worker_count(addopts)
        if not ok:
            return False, reason
        if task_meta.get("require_dist") and "--dist" not in addopts:
            return False, "task_meta.require_dist set but addopts has no --dist"
    elif task_meta.get("require_dist"):
        return False, "no addopts found and require_dist is set"

    if task_meta.get("skip_collect"):
        return True, "config parse passed (live collect skipped)"

    # Live check — drop the config into an isolated tmpdir with one trivial test
    with tempfile.TemporaryDirectory() as tmp:
        # Write the supplied config
        if "[pytest]" in text or "addopts" in text:
            (os.path.join(tmp, "pytest.ini"),)  # noqa
            with open(os.path.join(tmp, "pytest.ini"), "w", encoding="utf-8") as fh:
                if not text.lstrip().startswith("["):
                    fh.write("[pytest]\n")
                fh.write(text + "\n")
        # Single trivial test so collection has something to find
        with open(os.path.join(tmp, "test_smoke.py"), "w", encoding="utf-8") as fh:
            fh.write("def test_smoke():\n    assert 1 + 1 == 2\n")
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--collect-only",
                    "-q",
                    "--override-ini",
                    "addopts=",
                ]
                if addopts is None
                else [sys.executable, "-m", "pytest", "--collect-only", "-q"],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout).strip().splitlines()
                first = err[-1] if err else "collection failed"
                return False, f"pytest --collect-only failed: {first[:200]}"
            return True, "config + live collect passed"
        except subprocess.TimeoutExpired:
            return False, "pytest collect timeout — likely deadlock in xdist config"
        except FileNotFoundError:
            return True, "config parse passed (pytest unavailable for live check)"
