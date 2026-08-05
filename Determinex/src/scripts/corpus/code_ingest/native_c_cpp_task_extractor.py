"""
Native C/C++ repair task extractor.

Initial mutation class: null-guard removal. The extractor proves the baseline,
mutates one `if (ptr == NULL)` / `if (ptr == nullptr)` guard to `if (0)`,
confirms the native test oracle fails, and restores the original file.
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

_NULL_GUARD_RE = re.compile(
    r"^(?P<indent>[ \t]*)if\s*\(\s*(?P<expr>[\w.\->]+)\s*(==|!=)\s*(NULL|nullptr|0)\s*\)\s*\{",
    re.M,
)


@dataclass
class NativeRepairTask:
    task_id: str
    source_file: str
    original_line: str
    mutated_line: str
    line_number: int
    mutation_type: str
    failure_output: str
    failure_type: str
    repair_patch: str = ""
    build_system: str = "native"
    framework: str = "c_cpp"
    verdict: str = "pass"

    def to_corpus_payload(self) -> dict[str, Any]:
        return {
            "language": "c_cpp",
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
            "validator": "native project test command",
            "verdict": self.verdict,
            "task_id": self.task_id,
        }


class NativeTaskExtractor:
    def __init__(
        self, project_root: Path, test_command: list[str] | None = None, timeout: int = 120
    ):
        self._root = project_root
        self._timeout = timeout
        self._test_command = test_command or _default_test_command(project_root)

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
        rc, stdout, stderr = self._run(self._test_command)
        if rc == 0:
            return True, ""
        return False, (stdout + stderr)[:500]

    def find_native_sources(self) -> list[Path]:
        exts = {".c", ".cc", ".cpp", ".cxx"}
        result = []
        for p in self._root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in exts:
                continue
            rel = str(p.relative_to(self._root)).replace("\\", "/")
            if rel.startswith((".git/", "build/", "vendor/")):
                continue
            result.append(p)
        return result

    def find_null_guard_sites(self, source_file: Path) -> list[dict]:
        try:
            text = source_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        sites = []
        for m in _NULL_GUARD_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            line = m.group(0)
            if line.lstrip().startswith("//"):
                continue
            sites.append(
                {
                    "file": source_file,
                    "line_number": line_no,
                    "original": line,
                    "indent": m.group("indent"),
                    "relative_path": _safe_relative(source_file, self._root),
                }
            )
        return sites

    def _mutate_null_guard(self, text: str, site: dict) -> str:
        return text.replace(site["original"], f"{site['indent']}if (0) {{", 1)

    def _apply_mutation(self, source_file: Path, site: dict) -> tuple[str, str]:
        original = source_file.read_text(encoding="utf-8")
        mutated = self._mutate_null_guard(original, site)
        source_file.write_text(mutated, encoding="utf-8")
        return original, mutated

    def extract_tasks(self, max_tasks: int = 10) -> list[NativeRepairTask]:
        ok, err = self.verify_baseline()
        if not ok:
            log.warning("[native_extractor] baseline failed for %s: %s", self._root, err[:200])
            return []
        tasks: list[NativeRepairTask] = []
        for source_file in self.find_native_sources():
            if len(tasks) >= max_tasks:
                break
            for site in self.find_null_guard_sites(source_file)[:3]:
                if len(tasks) >= max_tasks:
                    break
                task = self._try_site(site)
                if task is not None:
                    tasks.append(task)
        return tasks

    def _try_site(self, site: dict) -> NativeRepairTask | None:
        source_file: Path = site["file"]
        original, mutated = self._apply_mutation(source_file, site)
        try:
            rc, stdout, stderr = self._run(self._test_command)
            if rc == 0:
                return None
            output = (stdout + stderr)[:500]
            return NativeRepairTask(
                task_id=_make_task_id(site["relative_path"], site["line_number"]),
                source_file=site["relative_path"],
                original_line=site["original"],
                mutated_line=f"{site['indent']}if (0) {{",
                line_number=site["line_number"],
                mutation_type="null_guard_removal",
                failure_output=output,
                failure_type=_classify_failure(output),
                repair_patch=_unified_diff(str(source_file), original, mutated),
            )
        finally:
            source_file.write_text(original, encoding="utf-8")


def _default_test_command(root: Path) -> list[str]:
    if (root / "CMakeLists.txt").is_file():
        return ["ctest", "--output-on-failure"]
    if (root / "Makefile").is_file() or (root / "makefile").is_file():
        return ["make", "test"]
    return ["true"]


def _classify_failure(output: str) -> str:
    lower = output.lower()
    if "segmentation fault" in lower or "asan" in lower or "null" in lower:
        return "memory_safety"
    if "undefined reference" in lower or "linker" in lower:
        return "linker_error"
    if "error:" in lower:
        return "compile_error"
    return "test_failure"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def _make_task_id(rel_path: str, line_number: int) -> str:
    digest = hashlib.blake2b(f"{rel_path}:{line_number}".encode(), digest_size=8).hexdigest()
    return f"native_null_{digest}"


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
