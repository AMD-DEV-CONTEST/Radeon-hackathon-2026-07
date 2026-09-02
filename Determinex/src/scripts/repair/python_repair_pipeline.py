"""
Python repair pipeline — license-gated, setup-file-scanned, corpus-signed.

Factory stages:
  1. License gate        — only green-bucket repos enter
  2. Secret scan         — no credentials in source tree
  3. Setup file gate     — setup.py / pyproject.toml scanned for injection patterns
  4. Baseline verify     — python -m pytest must pass before mutation
  5. Task extraction     — None-guard mutation → failure confirmation → restore
  6. Corpus write        — HMAC-signed PythonRepairTask records

The setup.py gate matters because setup.py runs arbitrary Python code during
`pip install`. A malicious setup.py could exfiltrate secrets or execute payloads.

Usage (production):
    cm = CorpusManager(root=Path("T:/determinex_corpus"))
    pipeline = PythonRepairPipeline(corpus_manager=cm)
    result = pipeline.process_repo(Path("/repos/my-project"), "swebench")

Usage (testing):
    call_n = {"n": 0}
    def fake_exec(cmd, cwd, timeout):
        call_n["n"] += 1
        if call_n["n"] == 1:
            return (0, "1 passed", "")       # baseline passes
        return (1, "FAILED", "AttributeError: 'NoneType' object")

    pipeline = PythonRepairPipeline(corpus_manager=cm, executor=fake_exec)

Implements LanguageRepairBackend.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.prompt_injection_detector import InjectionRisk
from agents.prompt_injection_detector import scan as injection_scan
from corpus.code_ingest.license_detector import detect
from corpus.code_ingest.python_task_extractor import PythonRepairTask, PythonTaskExtractor
from corpus.code_ingest.secret_scanner import is_clean as secrets_clean
from intake.hardened_runner import run as _hardened_run

log = logging.getLogger(__name__)

Executor = Callable[[list[str], Path, int], tuple[int, str, str]]

_SETUP_FILES = ("setup.py", "pyproject.toml", "setup.cfg")


def _default_executor(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    # As of HARDENED_REPAIR_PIPELINE_EXECUTORS_LOCK_001 this delegates to
    # intake.hardened_runner.run, which enforces argv-list, workspace-scoped
    # cwd, scrubbed env, no shell=True, and refuses Docker/network commands
    # by default. The historical contract is preserved:
    #   normal      -> (returncode, stdout, stderr)
    #   timed out   -> (-1, "", "TIMEOUT")
    #   tool missing-> (-2, "", error_message)
    #   blocked     -> (-3, "", "BLOCKED: <reason>")   # new code
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
class SetupFileSafetyResult:
    safe: bool
    reason: str
    file_path: str


class PythonRepairPipeline:
    """
    Full Python repair factory:
      license gate → secret scan → setup file gate → baseline → mutation → corpus write.
    """

    def __init__(
        self,
        corpus_manager: Any,
        executor: Executor | None = None,
        max_tasks_per_repo: int = 10,
        build_timeout: int = 60,
        source_benchmark: str = "python_corpus",
    ):
        self._cm = corpus_manager
        self._executor = executor or _default_executor
        self._max_tasks = max_tasks_per_repo
        self._timeout = build_timeout
        self._benchmark = source_benchmark

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_repo(self, repo_path: Path, source_benchmark: str | None = None) -> PipelineResult:
        """Run the full pipeline on a Python repo. Returns PipelineResult."""
        benchmark = source_benchmark or self._benchmark
        result = PipelineResult(repo_path=str(repo_path), tasks_extracted=0, tasks_written=0)

        # 1. License gate
        license_result = detect(repo_path)
        result.license_spdx = license_result.spdx_id or "unknown"
        result.license_bucket = license_result.bucket
        if not license_result.ingest_allowed:
            result.rejected_reason = (
                f"license_not_green:{result.license_spdx}:{result.license_bucket}"
            )
            log.info("[python_pipeline] rejected %s — %s", repo_path, result.rejected_reason)
            return result

        # 2. Secret scan
        if not secrets_clean(repo_path):
            result.rejected_reason = "secret_detected"
            log.info("[python_pipeline] rejected %s — secrets detected", repo_path)
            return result

        # 3. Setup file safety gate
        setup_safety = self._check_setup_file_safety(repo_path)
        if not setup_safety.safe:
            result.rejected_reason = f"malicious_setup_file:{setup_safety.reason}"
            log.warning("[python_pipeline] rejected %s — %s", repo_path, result.rejected_reason)
            return result

        # 4. Extract repair tasks
        tasks = self._extract_tasks(repo_path)
        result.tasks_extracted = len(tasks)

        # 5. Write corpus records
        for task in tasks:
            task_id = self._write_corpus_record(task, benchmark)
            if task_id:
                result.task_ids.append(task_id)
                result.tasks_written += 1

        return result

    # ------------------------------------------------------------------
    # Gate: setup.py / pyproject.toml safety
    # ------------------------------------------------------------------

    def _check_setup_file_safety(self, repo_path: Path) -> SetupFileSafetyResult:
        """
        Scan setup.py and pyproject.toml for injection / supply chain patterns.
        setup.py executes arbitrary code during install; malicious ones call
        out to remote servers or dump environment variables.
        """
        for filename in _SETUP_FILES:
            setup_file = repo_path / filename
            if not setup_file.exists():
                continue
            try:
                content = setup_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scan_result = injection_scan(content, source=str(setup_file))
            if scan_result.risk in (InjectionRisk.HIGH, InjectionRisk.CRITICAL):
                finding = scan_result.findings[0] if scan_result.findings else None
                reason = (
                    f"injection_risk:{scan_result.risk.value}"
                    f":{finding.pattern_name if finding else 'unknown'}"
                )
                return SetupFileSafetyResult(safe=False, reason=reason, file_path=str(setup_file))
        return SetupFileSafetyResult(safe=True, reason="", file_path="")

    # ------------------------------------------------------------------
    # Extraction with injectable executor
    # ------------------------------------------------------------------

    def _extract_tasks(self, repo_path: Path) -> list[PythonRepairTask]:
        """Run PythonTaskExtractor, substituting our executor for subprocess."""
        extractor = PythonTaskExtractor(repo_path, timeout=self._timeout)
        pipeline_self = self

        def _patched_run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
            return pipeline_self._executor(cmd, cwd or repo_path, pipeline_self._timeout)

        extractor._run = _patched_run  # type: ignore[method-assign]
        return extractor.extract_tasks(max_tasks=self._max_tasks)

    # ------------------------------------------------------------------
    # Corpus write
    # ------------------------------------------------------------------

    def _write_corpus_record(self, task: PythonRepairTask, benchmark: str) -> str | None:
        """Write a PythonRepairTask to corpus as a signed record."""
        try:
            from agents.base_agent import CorpusType

            payload = task.to_corpus_payload()
            input_hash = hashlib.blake2b(
                (task.mutated_block + task.failure_output).encode(),
                digest_size=16,
            ).hexdigest()
            output_hash = hashlib.blake2b(
                task.original_block.encode(),
                digest_size=16,
            ).hexdigest()
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
            log.error("[python_pipeline] failed to write corpus record %s: %s", task.task_id, e)
            return None

    # ------------------------------------------------------------------
    # Test factory
    # ------------------------------------------------------------------

    @classmethod
    def make_test_task(
        cls,
        task_id: str = "test-python-001",
        mutation_type: str = "none_guard_removal",
        failure_type: str = "attribute_error",
        build_system: str = "pytest",
        failure_output: str = "AttributeError: 'NoneType' object has no attribute 'strip'",
        original_block: str = "    if value is None:\n        raise ValueError('value required')",
        mutated_block: str = "    if False:\n        raise ValueError('value required')",
        verdict: str = "pass",
    ) -> PythonRepairTask:
        """Create a synthetic PythonRepairTask for testing corpus write."""
        return PythonRepairTask(
            task_id=task_id,
            source_file="src/utils.py",
            original_block=original_block,
            mutated_block=mutated_block,
            line_number=15,
            mutation_type=mutation_type,
            failure_output=failure_output,
            failure_type=failure_type,
            repair_patch=(
                "--- a/src/utils.py\n+++ b/src/utils.py\n"
                "@@ -15,2 +15,2 @@\n"
                f"-{mutated_block.splitlines()[0].strip()}\n"
                f"+{original_block.splitlines()[0].strip()}\n"
            ),
            build_system=build_system,
            verdict=verdict,
        )
