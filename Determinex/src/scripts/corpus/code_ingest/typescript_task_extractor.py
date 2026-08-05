"""
TypeScript repair task extractor.

Initial mutation class: optional-chain removal. The extractor proves baseline,
mutates `obj?.prop` to `obj.prop`, confirms tests/typecheck fail, and restores
the original file.
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

_OPTIONAL_CHAIN_RE = re.compile(r"(?P<expr>\b[A-Za-z_$][\w$]*)\?\.(?P<prop>[A-Za-z_$][\w$]*)")


@dataclass
class TypeScriptRepairTask:
    task_id: str
    source_file: str
    original_snippet: str
    mutated_snippet: str
    line_number: int
    mutation_type: str
    failure_output: str
    failure_type: str
    repair_patch: str = ""
    build_system: str = "npm"
    framework: str = "typescript"
    verdict: str = "pass"

    def to_corpus_payload(self) -> dict[str, Any]:
        return {
            "language": "typescript",
            "build_system": self.build_system,
            "framework": self.framework,
            "mutation_type": self.mutation_type,
            "failure_type": self.failure_type,
            "source_file": self.source_file,
            "original_snippet": self.original_snippet.strip()[:300],
            "mutated_snippet": self.mutated_snippet.strip()[:300],
            "line_number": self.line_number,
            "failure_output": self.failure_output[:500],
            "repair_patch": self.repair_patch[:2000],
            "validator": "npm test / tsc --noEmit",
            "verdict": self.verdict,
            "task_id": self.task_id,
        }


class TypeScriptTaskExtractor:
    def __init__(
        self, project_root: Path, baseline_command: list[str] | None = None, timeout: int = 90
    ):
        self._root = project_root
        self._timeout = timeout
        self._baseline_command = baseline_command or ["npm", "test", "--", "--runInBand"]

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
        rc, stdout, stderr = self._run(self._baseline_command)
        if rc == 0:
            return True, ""
        return False, (stdout + stderr)[:500]

    def find_sources(self) -> list[Path]:
        exts = {".ts", ".tsx", ".js", ".jsx"}
        excluded = {"node_modules", "dist", "build", ".git", "coverage"}
        result = []
        for p in self._root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in exts:
                continue
            rel_parts = set(p.relative_to(self._root).parts)
            if rel_parts.intersection(excluded):
                continue
            result.append(p)
        return result

    def find_optional_chain_sites(self, source_file: Path) -> list[dict]:
        try:
            text = source_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        sites = []
        for m in _OPTIONAL_CHAIN_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            sites.append(
                {
                    "file": source_file,
                    "line_number": line_no,
                    "original": m.group(0),
                    "mutated": f"{m.group('expr')}.{m.group('prop')}",
                    "relative_path": _safe_relative(source_file, self._root),
                }
            )
        return sites

    def _apply_mutation(self, source_file: Path, site: dict) -> tuple[str, str]:
        original = source_file.read_text(encoding="utf-8")
        mutated = original.replace(site["original"], site["mutated"], 1)
        source_file.write_text(mutated, encoding="utf-8")
        return original, mutated

    def extract_tasks(self, max_tasks: int = 10) -> list[TypeScriptRepairTask]:
        ok, err = self.verify_baseline()
        if not ok:
            log.warning("[ts_extractor] baseline failed for %s: %s", self._root, err[:200])
            return []
        tasks: list[TypeScriptRepairTask] = []
        for source_file in self.find_sources():
            if len(tasks) >= max_tasks:
                break
            for site in self.find_optional_chain_sites(source_file)[:3]:
                if len(tasks) >= max_tasks:
                    break
                task = self._try_site(site)
                if task is not None:
                    tasks.append(task)
        return tasks

    def _try_site(self, site: dict) -> TypeScriptRepairTask | None:
        source_file: Path = site["file"]
        original, mutated = self._apply_mutation(source_file, site)
        try:
            rc, stdout, stderr = self._run(self._baseline_command)
            if rc == 0:
                return None
            output = (stdout + stderr)[:500]
            return TypeScriptRepairTask(
                task_id=_make_task_id(site["relative_path"], site["line_number"]),
                source_file=site["relative_path"],
                original_snippet=site["original"],
                mutated_snippet=site["mutated"],
                line_number=site["line_number"],
                mutation_type="optional_chain_removal",
                failure_output=output,
                failure_type=_classify_failure(output),
                repair_patch=_unified_diff(str(source_file), original, mutated),
            )
        finally:
            source_file.write_text(original, encoding="utf-8")


def _classify_failure(output: str) -> str:
    lower = output.lower()
    if "typeerror" in lower or "cannot read" in lower:
        return "runtime_type_error"
    if "ts" in lower and "error" in lower:
        return "type_error"
    if "expect" in lower or "failed" in lower:
        return "test_failure"
    return "typescript_failure"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def _make_task_id(rel_path: str, line_number: int) -> str:
    digest = hashlib.blake2b(f"{rel_path}:{line_number}".encode(), digest_size=8).hexdigest()
    return f"ts_optional_{digest}"


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
