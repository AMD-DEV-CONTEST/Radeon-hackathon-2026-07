"""
Python repair task extractor.

Given a Python project, extracts repair tasks by:
  1. Running python -m pytest to confirm the baseline is green
  2. Scanning source files for None-guard candidates
  3. Applying one mutation per candidate (replace guard with `if False:`)
  4. Running pytest to confirm the mutation causes failure
  5. Restoring the file and recording the (mutation, failure) trace

Mutation types:
  - none_guard_removal: replace `if x is None: raise/return` with `if False:`
  - assert_removal: replace `assert condition` with `assert True`
  - wrong_default: replace default argument value with None

The _run method is designed for monkey-patching in tests:
    extractor._run = lambda cmd, cwd=None: (0, "1 passed", "")
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# None guard: `if x is None:` at any indent level
_NONE_GUARD_RE = re.compile(r"^(?P<indent>[ \t]*)if\s+\w+\s+is\s+None\s*:", re.M)
# Assert statement: `assert <expr>` not followed by True
_ASSERT_RE = re.compile(r"^(?P<indent>[ \t]*)assert\s+(?!True\b)(?P<expr>[^\n]+)", re.M)


@dataclass
class PythonRepairTask:
    task_id: str
    source_file: str
    original_block: str
    mutated_block: str
    line_number: int
    mutation_type: str  # "none_guard_removal" | "assert_removal"
    failure_output: str
    failure_type: str  # "assertion_error" | "attribute_error" | "type_error" | "test_failure"
    repair_patch: str = ""
    build_system: str = "pytest"
    framework: str = "python"
    verdict: str = "pass"

    def to_corpus_payload(self) -> dict[str, Any]:
        return {
            "language": "python",
            "build_system": self.build_system,
            "framework": self.framework,
            "mutation_type": self.mutation_type,
            "failure_type": self.failure_type,
            "source_file": self.source_file,
            "original_block": self.original_block.strip()[:300],
            "mutated_block": self.mutated_block.strip()[:300],
            "line_number": self.line_number,
            "failure_output": self.failure_output[:500],
            "repair_patch": self.repair_patch[:2000],
            "validator": "python -m pytest",
            "verdict": self.verdict,
            "task_id": self.task_id,
        }


class PythonTaskExtractor:
    """
    Extracts Python repair tasks by mutation → failure confirmation → restore.

    Args:
        project_root: Path to directory containing pyproject.toml / setup.py.
        timeout: Seconds to wait for pytest.
    """

    def __init__(self, project_root: Path, timeout: int = 60):
        self._root = project_root
        self._timeout = timeout

    def _run(self, cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
        """Execute a command. Monkey-patch this in tests."""
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd or self._root,
                timeout=self._timeout,
            )
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "TIMEOUT"
        except FileNotFoundError as e:
            return -2, "", str(e)

    # ------------------------------------------------------------------
    # Baseline verification
    # ------------------------------------------------------------------

    def verify_baseline(self) -> tuple[bool, str]:
        """Run python -m pytest -q. Return (passed, error_msg)."""
        rc, stdout, stderr = self._run(["python", "-m", "pytest", "-q", "--tb=no", "--no-header"])
        if rc == 0:
            return True, ""
        return False, (stdout + stderr)[:500]

    # ------------------------------------------------------------------
    # Candidate discovery
    # ------------------------------------------------------------------

    def find_python_sources(self) -> list[Path]:
        """All .py files under project root, excluding common non-source dirs."""
        excluded = {
            ".venv",
            "venv",
            "env",
            ".env",
            "__pycache__",
            ".tox",
            ".nox",
            "dist",
            "build",
            ".git",
            "node_modules",
        }
        result = []
        for p in self._root.rglob("*.py"):
            parts = set(p.parts)
            if not parts.intersection(excluded):
                result.append(p)
        return result

    def find_none_guard_sites(self, py_file: Path) -> list[dict]:
        """Find `if x is None:` blocks that guard a raise or return."""
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        lines = text.splitlines()
        sites = []
        for m in _NONE_GUARD_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            # Check that the next non-empty line is a raise or return
            body_start = line_no  # 0-indexed into lines
            if body_start < len(lines):
                next_line = lines[body_start].strip() if body_start < len(lines) else ""
                if next_line.startswith(("raise", "return")):
                    sites.append(
                        {
                            "file": py_file,
                            "line_number": line_no,
                            "original": m.group(0),
                            "indent": m.group("indent"),
                            "relative_path": _safe_relative(py_file, self._root),
                        }
                    )
        return sites

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def _mutate_none_guard(self, text: str, site: dict) -> str:
        """Replace `if x is None:` with `if False:`."""
        original = site["original"]
        indent = site["indent"]
        replacement = f"{indent}if False:"
        return text.replace(original, replacement, 1)

    def _apply_mutation(self, py_file: Path, site: dict) -> tuple[str, str]:
        """Write mutation; return (original_content, mutated_content)."""
        try:
            from hive.workspace import assert_inside_workspace

            assert_inside_workspace(py_file, self._root)
        except (ImportError, ValueError) as _esc:
            raise ValueError(f"Workspace escape blocked before mutation write: {_esc}") from _esc
        original = py_file.read_text(encoding="utf-8")
        mutated = self._mutate_none_guard(original, site)
        py_file.write_text(mutated, encoding="utf-8")
        return original, mutated

    # ------------------------------------------------------------------
    # Task extraction
    # ------------------------------------------------------------------

    def extract_tasks(self, max_tasks: int = 10) -> list[PythonRepairTask]:
        """
        Full extraction loop:
          1. verify_baseline — abort if failing
          2. for each None guard site: mutate → confirm failure → restore
          3. return tasks (up to max_tasks)
        """
        ok, err = self.verify_baseline()
        if not ok:
            log.warning("[python_extractor] baseline failed for %s: %s", self._root, err[:200])
            return []

        tasks: list[PythonRepairTask] = []
        sources = self.find_python_sources()

        for py_file in sources:
            if len(tasks) >= max_tasks:
                break
            sites = self.find_none_guard_sites(py_file)
            for site in sites[:3]:
                if len(tasks) >= max_tasks:
                    break
                task = self._try_site(site)
                if task is not None:
                    tasks.append(task)

        return tasks

    def _try_site(self, site: dict) -> PythonRepairTask | None:
        """Apply mutation, run pytest, restore. Return task or None."""
        py_file: Path = site["file"]
        original, mutated = self._apply_mutation(py_file, site)
        try:
            rc, stdout, stderr = self._run(
                ["python", "-m", "pytest", "-q", "--tb=short", "--no-header"]
            )
            if rc == 0:
                return None  # mutation had no observable effect

            failure_output = (stdout + stderr)[:500]
            failure_type = _classify_failure(stdout + stderr)
            mutated_block = self._mutate_none_guard(site["original"], site)
            patch = _unified_diff(str(py_file), original, mutated)
            task_id = _make_task_id(site["relative_path"], site["line_number"])

            return PythonRepairTask(
                task_id=task_id,
                source_file=site["relative_path"],
                original_block=site["original"],
                mutated_block=mutated_block,
                line_number=site["line_number"],
                mutation_type="none_guard_removal",
                failure_output=failure_output,
                failure_type=failure_type,
                repair_patch=patch,
            )
        finally:
            py_file.write_text(original, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_failure(output: str) -> str:
    lower = output.lower()
    if "attributeerror" in lower:
        return "attribute_error"
    if "assertionerror" in lower or "assert" in lower:
        return "assertion_error"
    if "typeerror" in lower:
        return "type_error"
    if "syntaxerror" in lower or "error:" in lower:
        return "syntax_error"
    return "test_failure"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _make_task_id(rel_path: str, line_number: int) -> str:
    digest = hashlib.blake2b(
        f"{rel_path}:{line_number}".encode(),
        digest_size=8,
    ).hexdigest()
    return f"python_none_{digest}"


def _unified_diff(path: str, original: str, mutated: str) -> str:
    return "".join(
        difflib.unified_diff(
            mutated.splitlines(keepends=True),
            original.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
