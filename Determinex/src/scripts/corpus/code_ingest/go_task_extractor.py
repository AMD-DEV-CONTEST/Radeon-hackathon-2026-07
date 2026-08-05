"""
Go repair task extractor.

The first Go mutation class is nil-guard removal. The extractor proves a
baseline with `go test ./...`, mutates one guard to `if false {`, confirms
the tests fail, then restores the source file before returning the task.
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

_NIL_GUARD_RE = re.compile(r"^(?P<indent>[ \t]*)if\s+(?P<expr>[\w.]+)\s*==\s*nil\s*\{", re.M)


@dataclass
class GoRepairTask:
    task_id: str
    source_file: str
    original_line: str
    mutated_line: str
    line_number: int
    mutation_type: str
    failure_output: str
    failure_type: str
    repair_patch: str = ""
    build_system: str = "go_modules"
    framework: str = "go"
    verdict: str = "pass"

    def to_corpus_payload(self) -> dict[str, Any]:
        return {
            "language": "go",
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
            "validator": "go test ./...",
            "verdict": self.verdict,
            "task_id": self.task_id,
        }


class GoTaskExtractor:
    def __init__(self, project_root: Path, timeout: int = 90):
        self._root = project_root
        self._timeout = timeout

    def _run(self, cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd or self._root, timeout=self._timeout
            )
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "TIMEOUT"
        except FileNotFoundError as e:
            return -2, "", str(e)

    def verify_baseline(self) -> tuple[bool, str]:
        rc, stdout, stderr = self._run(["go", "test", "./..."])
        if rc == 0:
            return True, ""
        return False, (stdout + stderr)[:500]

    def find_go_sources(self) -> list[Path]:
        excluded = {"vendor", ".git", "testdata"}
        result = []
        for p in self._root.rglob("*.go"):
            parts = set(p.parts)
            rel = str(p.relative_to(self._root)).replace("\\", "/")
            if parts.intersection(excluded):
                continue
            if rel.endswith("_test.go"):
                continue
            result.append(p)
        return result

    def find_nil_guard_sites(self, go_file: Path) -> list[dict]:
        try:
            text = go_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        sites = []
        for m in _NIL_GUARD_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            line = m.group(0)
            if line.lstrip().startswith("//"):
                continue
            sites.append(
                {
                    "file": go_file,
                    "line_number": line_no,
                    "original": line,
                    "indent": m.group("indent"),
                    "relative_path": _safe_relative(go_file, self._root),
                }
            )
        return sites

    def _mutate_nil_guard(self, text: str, site: dict) -> str:
        return text.replace(site["original"], f"{site['indent']}if false {{", 1)

    def _apply_mutation(self, go_file: Path, site: dict) -> tuple[str, str]:
        original = go_file.read_text(encoding="utf-8")
        mutated = self._mutate_nil_guard(original, site)
        go_file.write_text(mutated, encoding="utf-8")
        return original, mutated

    def extract_tasks(self, max_tasks: int = 10) -> list[GoRepairTask]:
        ok, err = self.verify_baseline()
        if not ok:
            log.warning("[go_extractor] baseline failed for %s: %s", self._root, err[:200])
            return []

        tasks: list[GoRepairTask] = []
        for go_file in self.find_go_sources():
            if len(tasks) >= max_tasks:
                break
            for site in self.find_nil_guard_sites(go_file)[:3]:
                if len(tasks) >= max_tasks:
                    break
                task = self._try_site(site)
                if task is not None:
                    tasks.append(task)
        return tasks

    def _try_site(self, site: dict) -> GoRepairTask | None:
        go_file: Path = site["file"]
        original, mutated = self._apply_mutation(go_file, site)
        try:
            rc, stdout, stderr = self._run(["go", "test", "./..."])
            if rc == 0:
                return None
            failure_output = (stdout + stderr)[:500]
            failure_type = _classify_failure(stdout + stderr)
            mutated_line = f"{site['indent']}if false {{"
            return GoRepairTask(
                task_id=_make_task_id(site["relative_path"], site["line_number"]),
                source_file=site["relative_path"],
                original_line=site["original"],
                mutated_line=mutated_line,
                line_number=site["line_number"],
                mutation_type="nil_guard_removal",
                failure_output=failure_output,
                failure_type=failure_type,
                repair_patch=_unified_diff(str(go_file), original, mutated),
            )
        finally:
            go_file.write_text(original, encoding="utf-8")


def _classify_failure(output: str) -> str:
    lower = output.lower()
    if "panic:" in lower or "nil pointer" in lower:
        return "panic"
    if "build failed" in lower or "syntax error" in lower or "undefined:" in lower:
        return "compile_error"
    if "--- fail:" in lower or "failed" in lower:
        return "test_failure"
    return "go_test_failure"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def _make_task_id(rel_path: str, line_number: int) -> str:
    digest = hashlib.blake2b(f"{rel_path}:{line_number}".encode(), digest_size=8).hexdigest()
    return f"go_nil_{digest}"


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
