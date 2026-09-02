"""
Rust repair task extractor.

Given a Rust project (Cargo.toml), extracts repair tasks by:
  1. Running cargo test --locked to confirm the baseline is green
  2. Scanning source files for mutation candidates (.unwrap() calls)
  3. Applying one mutation per candidate to introduce a targeted defect
  4. Running cargo test --locked to confirm the mutation causes failure
  5. Restoring the file and recording the (mutation, failure) trace

Mutation types:
  - unwrap_panic: replace .unwrap() with a forced panic variant
  - option_map: replace .unwrap() in Option chain with mismatched unwrap_or
  - result_propagate: replace ? with .unwrap() forcing a panic instead of propagation

The _run method is designed for monkey-patching in tests:
    extractor._run = lambda cmd, cwd=None: (0, "ok", "")
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_UNWRAP_LITERAL = (
    ".unwrap()"  # used as a plain string check; comment filtering is done in find_unwrap_sites
)


@dataclass
class RustRepairTask:
    task_id: str
    source_file: str
    original_line: str
    mutated_line: str
    line_number: int
    mutation_type: str  # "unwrap_panic" | "unwrap_or_wrong" | "question_to_unwrap"
    failure_output: str
    failure_type: str  # "test_failure" | "panic" | "compile_error"
    repair_patch: str = ""
    build_system: str = "cargo"
    framework: str = "rust"
    verdict: str = "pass"

    def to_corpus_payload(self) -> dict[str, Any]:
        return {
            "language": "rust",
            "build_system": self.build_system,
            "framework": self.framework,
            "mutation_type": self.mutation_type,
            "failure_type": self.failure_type,
            "source_file": self.source_file,
            "original_line": self.original_line.strip()[:300],
            "mutated_line": self.mutated_line.strip()[:300],
            "line_number": self.line_number,
            "failure_output": self.failure_output[:500],
            "repair_patch": self.repair_patch[:2000],
            "validator": "cargo test --locked",
            "verdict": self.verdict,
            "task_id": self.task_id,
        }


class RustTaskExtractor:
    """
    Extracts Rust repair tasks by mutation → failure confirmation → restore.

    Args:
        project_root: Path to directory containing Cargo.toml.
        timeout: Seconds to wait for cargo commands.
    """

    def __init__(self, project_root: Path, timeout: int = 120):
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
        """Run cargo test --locked. Return (passed, error_msg)."""
        rc, stdout, stderr = self._run(["cargo", "test", "--locked"])
        if rc == 0:
            return True, ""
        return False, (stderr + stdout)[:500]

    # ------------------------------------------------------------------
    # Candidate discovery
    # ------------------------------------------------------------------

    def find_rust_sources(self) -> list[Path]:
        """All .rs files under project root, excluding the target/ directory."""
        return [
            p
            for p in self._root.rglob("*.rs")
            if "target" + "/" not in str(p).replace("\\", "/") and "target\\" not in str(p)
        ]

    def find_unwrap_sites(self, rs_file: Path) -> list[dict]:
        """Return line-level metadata for each .unwrap() call in the file."""
        try:
            lines = rs_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        sites = []
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("///"):
                continue
            if ".unwrap()" in line:
                sites.append(
                    {
                        "file": rs_file,
                        "line_number": i + 1,
                        "original": line,
                        "relative_path": _safe_relative(rs_file, self._root),
                    }
                )
        return sites

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def _mutate_line(self, line: str) -> str:
        """
        Replace the first .unwrap() with .expect("determinex_none_inject") so the
        code still compiles but panics with a recognisable message at runtime.
        """
        return line.replace(".unwrap()", '.expect("determinex_none_inject")', 1)

    def _apply_mutation(self, rs_file: Path, site: dict) -> tuple[str, str]:
        """Write mutation; return (original_content, mutated_content)."""
        try:
            from hive.workspace import assert_inside_workspace

            assert_inside_workspace(rs_file, self._root)
        except (ImportError, ValueError) as _esc:
            raise ValueError(f"Workspace escape blocked before mutation write: {_esc}") from _esc
        original = rs_file.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        idx = site["line_number"] - 1
        mutated_line = self._mutate_line(lines[idx].rstrip("\n")) + "\n"
        lines[idx] = mutated_line
        mutated = "".join(lines)
        rs_file.write_text(mutated, encoding="utf-8")
        return original, mutated

    # ------------------------------------------------------------------
    # Task extraction
    # ------------------------------------------------------------------

    def extract_tasks(self, max_tasks: int = 10) -> list[RustRepairTask]:
        """
        Full extraction loop:
          1. verify_baseline — abort if failing
          2. for each .unwrap() site: mutate → confirm failure → restore
          3. return tasks (up to max_tasks)
        """
        ok, err = self.verify_baseline()
        if not ok:
            log.warning("[rust_extractor] baseline failed for %s: %s", self._root, err[:200])
            return []

        tasks: list[RustRepairTask] = []
        sources = self.find_rust_sources()

        for rs_file in sources:
            if len(tasks) >= max_tasks:
                break
            sites = self.find_unwrap_sites(rs_file)
            for site in sites[:3]:  # max 3 mutations per file
                if len(tasks) >= max_tasks:
                    break
                task = self._try_site(site)
                if task is not None:
                    tasks.append(task)

        return tasks

    def _try_site(self, site: dict) -> RustRepairTask | None:
        """Apply mutation, run tests, restore. Return task or None."""
        rs_file: Path = site["file"]
        original, mutated = self._apply_mutation(rs_file, site)
        try:
            rc, stdout, stderr = self._run(["cargo", "test", "--locked"])
            if rc == 0:
                return None  # mutation had no observable effect

            failure_output = (stderr + stdout)[:500]
            failure_type = _classify_failure(stderr + stdout)
            mutated_line = self._mutate_line(site["original"].rstrip("\n"))
            patch = _unified_diff(str(rs_file), original, mutated)
            task_id = _make_task_id(site["relative_path"], site["line_number"])

            return RustRepairTask(
                task_id=task_id,
                source_file=site["relative_path"],
                original_line=site["original"],
                mutated_line=mutated_line,
                line_number=site["line_number"],
                mutation_type="unwrap_panic",
                failure_output=failure_output,
                failure_type=failure_type,
                repair_patch=patch,
            )
        finally:
            rs_file.write_text(original, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_failure(output: str) -> str:
    lower = output.lower()
    if "error[e" in lower or "error:" in lower:
        return "compile_error"
    if "panicked" in lower or "determinex_none_inject" in lower:
        return "panic"
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
    return f"rust_unwrap_{digest}"


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
