"""
Go repair pipeline: license gate, secret scan, go:generate/build-file scan,
baseline verification, mutation extraction, and signed corpus writing.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.prompt_injection_detector import InjectionRisk
from agents.prompt_injection_detector import scan as injection_scan
from corpus.code_ingest.go_project_indexer import GoProject, index_go_project
from corpus.code_ingest.go_task_extractor import GoRepairTask, GoTaskExtractor
from corpus.code_ingest.license_detector import detect
from corpus.code_ingest.secret_scanner import is_clean as secrets_clean
from intake.hardened_runner import run as _hardened_run

log = logging.getLogger(__name__)

Executor = Callable[[list[str], Path, int], tuple[int, str, str]]

_BUILD_FILES = ("go.mod", "go.sum", "Makefile", "Taskfile.yml", "magefile.go")
_SUSPICIOUS_REPLACE_RE = re.compile(
    r"^\s*replace\s+\S+\s+=>\s+(\.\./|/|[A-Za-z]:\\|file:|\\\\)",
    re.M,
)
_SPOOFED_MODULES = {
    "std",
    "builtin",
    "github.com/golang/go",
    "golang.org/x/tools",
}
_INIT_NETWORK_RE = re.compile(
    r"func\s+init\s*\(\s*\)\s*\{[\s\S]{0,500}\b(http\.(Get|Post)|net\.Dial)\b",
    re.M,
)
_TESTMAIN_EXEC_RE = re.compile(
    r"func\s+TestMain\s*\([^)]*\)\s*\{[\s\S]{0,500}\bexec\.Command\b",
    re.M,
)


def _default_executor(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    # Delegates to intake.hardened_runner.run per
    # HARDENED_REPAIR_PIPELINE_EXECUTORS_LOCK_001. See python_repair_pipeline
    # for the negative-rc contract preserved here.
    r = _hardened_run(cmd, workspace=cwd, timeout=timeout)
    if r.blocked:
        return -3, "", f"BLOCKED: {r.reason}"
    if r.timed_out:
        return -1, "", "TIMEOUT"
    if r.tool_missing:
        return -2, "", r.stderr or f"tool not found: {cmd[0]}"
    return r.exit_code, r.stdout, r.stderr


@dataclass
class PipelineResult:
    repo_path: str
    tasks_extracted: int
    tasks_written: int
    rejected_reason: str = ""
    license_spdx: str = ""
    license_bucket: str = ""
    task_ids: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.rejected_reason


@dataclass
class GoSafetyResult:
    safe: bool
    reason: str
    file_path: str


class GoRepairPipeline:
    def __init__(
        self,
        corpus_manager: Any,
        executor: Executor | None = None,
        max_tasks_per_repo: int = 10,
        build_timeout: int = 90,
        source_benchmark: str = "go_corpus",
    ):
        self._cm = corpus_manager
        self._executor = executor or _default_executor
        self._max_tasks = max_tasks_per_repo
        self._timeout = build_timeout
        self._benchmark = source_benchmark

    def process_repo(self, repo_path: Path, source_benchmark: str | None = None) -> PipelineResult:
        benchmark = source_benchmark or self._benchmark
        result = PipelineResult(repo_path=str(repo_path), tasks_extracted=0, tasks_written=0)

        project = index_go_project(repo_path)
        if project is None:
            result.rejected_reason = "not_go_module"
            return result

        module_safety = self._check_module_safety(project)
        if not module_safety.safe:
            result.rejected_reason = f"unsafe_go_module:{module_safety.reason}"
            return result

        license_result = detect(repo_path)
        result.license_spdx = license_result.spdx_id or "unknown"
        result.license_bucket = license_result.bucket
        if not license_result.ingest_allowed:
            result.rejected_reason = (
                f"license_not_green:{result.license_spdx}:{result.license_bucket}"
            )
            return result

        if not secrets_clean(repo_path):
            result.rejected_reason = "secret_detected"
            return result

        safety = self._check_go_source_safety(repo_path)
        if not safety.safe:
            result.rejected_reason = f"malicious_go_source:{safety.reason}"
            return result

        if not self._check_gofmt(repo_path):
            result.rejected_reason = "gofmt_not_clean"
            return result

        tasks = self._extract_tasks(repo_path)
        result.tasks_extracted = len(tasks)
        for task in tasks:
            task_id = self._write_corpus_record(task, benchmark)
            if task_id:
                result.task_ids.append(task_id)
                result.tasks_written += 1
        return result

    def _check_module_safety(self, project: GoProject) -> GoSafetyResult:
        if project.module_path in _SPOOFED_MODULES:
            return GoSafetyResult(
                safe=False,
                reason=f"module_path_spoof:{project.module_path}",
                file_path=str(project.root / "go.mod"),
            )
        go_mod = project.root / "go.mod"
        try:
            content = go_mod.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return GoSafetyResult(safe=False, reason="go_mod_unreadable", file_path=str(go_mod))
        m = _SUSPICIOUS_REPLACE_RE.search(content)
        if m:
            return GoSafetyResult(
                safe=False,
                reason=f"suspicious_replace:{m.group(1)}",
                file_path=str(go_mod),
            )
        return GoSafetyResult(safe=True, reason="", file_path="")

    def _check_go_source_safety(self, repo_path: Path) -> GoSafetyResult:
        scan_files: list[Path] = []
        for name in _BUILD_FILES:
            p = repo_path / name
            if p.is_file():
                scan_files.append(p)
        for go_file in repo_path.rglob("*.go"):
            if "vendor" in go_file.parts:
                continue
            scan_files.append(go_file)

        for p in scan_files:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            custom = self._check_go_content_safety(content, p)
            if not custom.safe:
                return custom
            scan_result = injection_scan(content, source=str(p))
            if scan_result.risk in (InjectionRisk.HIGH, InjectionRisk.CRITICAL):
                finding = scan_result.findings[0] if scan_result.findings else None
                reason = f"injection_risk:{scan_result.risk.value}:{finding.pattern_name if finding else 'unknown'}"
                return GoSafetyResult(safe=False, reason=reason, file_path=str(p))
        return GoSafetyResult(safe=True, reason="", file_path="")

    def _check_go_content_safety(self, content: str, path: Path) -> GoSafetyResult:
        if _INIT_NETWORK_RE.search(content):
            return GoSafetyResult(safe=False, reason="init_network_call", file_path=str(path))
        if _TESTMAIN_EXEC_RE.search(content):
            return GoSafetyResult(safe=False, reason="testmain_exec_command", file_path=str(path))
        if "#cgo" in content and re.search(
            r"(curl\s+https?://|env\s*\|\s*curl|`|\$\()", content, re.I
        ):
            return GoSafetyResult(safe=False, reason="cgo_command_injection", file_path=str(path))
        return GoSafetyResult(safe=True, reason="", file_path="")

    def _check_gofmt(self, repo_path: Path) -> bool:
        files = [
            str(p.relative_to(repo_path)).replace("\\", "/")
            for p in repo_path.rglob("*.go")
            if "vendor" not in p.parts and ".git" not in p.parts
        ]
        if not files:
            return True
        rc, stdout, stderr = self._executor(["gofmt", "-l", *files], repo_path, self._timeout)
        return rc == 0 and not stdout.strip() and not stderr.strip()

    def _extract_tasks(self, repo_path: Path) -> list[GoRepairTask]:
        extractor = GoTaskExtractor(repo_path, timeout=self._timeout)
        pipeline_self = self

        def _patched_run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
            return pipeline_self._executor(cmd, cwd or repo_path, pipeline_self._timeout)

        extractor._run = _patched_run  # type: ignore[method-assign]
        return extractor.extract_tasks(max_tasks=self._max_tasks)

    def _write_corpus_record(self, task: GoRepairTask, benchmark: str) -> str | None:
        try:
            from agents.base_agent import CorpusType

            payload = task.to_corpus_payload()
            input_hash = hashlib.blake2b(
                (task.mutated_line + task.failure_output).encode(), digest_size=16
            ).hexdigest()
            output_hash = hashlib.blake2b(task.original_line.encode(), digest_size=16).hexdigest()
            record = self._cm._normalize_record(
                corpus_type=CorpusType.CODE_VERDICT,
                task_id=task.task_id,
                input_hash=input_hash,
                output_hash=output_hash,
                source_benchmark=benchmark,
                payload=payload,
            )
            self._cm._write_record(CorpusType.CODE_VERDICT, record)
            return task.task_id
        except Exception as e:
            log.error("[go_pipeline] failed to write corpus record %s: %s", task.task_id, e)
            return None

    @classmethod
    def make_test_task(
        cls,
        task_id: str = "test-go-001",
        mutation_type: str = "nil_guard_removal",
        failure_type: str = "panic",
        build_system: str = "go_modules",
        failure_output: str = "panic: runtime error: invalid memory address or nil pointer dereference",
        original_line: str = "if value == nil {",
        mutated_line: str = "if false {",
        verdict: str = "pass",
    ) -> GoRepairTask:
        return GoRepairTask(
            task_id=task_id,
            source_file="pkg/example/example.go",
            original_line=original_line,
            mutated_line=mutated_line,
            line_number=12,
            mutation_type=mutation_type,
            failure_output=failure_output,
            failure_type=failure_type,
            repair_patch=(
                "--- a/pkg/example/example.go\n+++ b/pkg/example/example.go\n"
                "@@ -12 +12 @@\n"
                f"-{mutated_line}\n"
                f"+{original_line}\n"
            ),
            build_system=build_system,
            verdict=verdict,
        )
