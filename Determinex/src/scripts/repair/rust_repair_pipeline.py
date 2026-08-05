"""
Rust repair pipeline — license-gated, build-script-scanned, corpus-signed.

Factory stages:
  1. License gate         — only green-bucket repos (MIT/Apache/BSD/ISC) enter
  2. Secret scan          — no credentials in source tree
  3. Build script gate    — build.rs scanned for injection / supply chain patterns
  4. Baseline verify      — cargo test --locked must pass before mutation
  5. Task extraction      — unwrap mutation → failure confirmation → restore
  6. Corpus write         — HMAC-signed RustRepairTask records

Usage (production):
    cm = CorpusManager(root=Path("T:/determinex_corpus"))
    pipeline = RustRepairPipeline(corpus_manager=cm)
    result = pipeline.process_repo(Path("/repos/angle-grinder"), "programbench")

Usage (testing):
    call_n = {"n": 0}
    def fake_exec(cmd, cwd, timeout):
        call_n["n"] += 1
        if call_n["n"] == 1:
            return (0, "test result: 3 passed", "")    # baseline passes
        return (1, "", "thread 'main' panicked at 'determinex_none_inject'")

    pipeline = RustRepairPipeline(corpus_manager=cm, executor=fake_exec)
    result = pipeline.process_repo(repo_path, "test_corpus")

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
from corpus.code_ingest.rust_task_extractor import RustRepairTask, RustTaskExtractor
from corpus.code_ingest.secret_scanner import is_clean as secrets_clean
from intake.hardened_runner import run as _hardened_run

log = logging.getLogger(__name__)

# (cmd, cwd, timeout) → (returncode, stdout, stderr)
Executor = Callable[[list[str], Path, int], tuple[int, str, str]]


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
class BuildScriptSafetyResult:
    safe: bool
    reason: str
    script_path: str


class RustRepairPipeline:
    """
    Full Rust repair factory:
      license gate → secret scan → build.rs gate → baseline → mutation → corpus write.

    Args:
        corpus_manager:    CorpusManager instance for writing signed records.
        executor:          Optional callable replacing subprocess. Signature:
                               (cmd: list[str], cwd: Path, timeout: int) → (rc, stdout, stderr)
        max_tasks_per_repo: Maximum repair tasks to extract per repo.
        build_timeout:     Seconds to wait for cargo commands.
        source_benchmark:  Default benchmark label for corpus records.
    """

    def __init__(
        self,
        corpus_manager: Any,
        executor: Executor | None = None,
        max_tasks_per_repo: int = 10,
        build_timeout: int = 120,
        source_benchmark: str = "rust_corpus",
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
        """Run the full pipeline on a Rust repo. Returns PipelineResult."""
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
            log.info("[rust_pipeline] rejected %s — %s", repo_path, result.rejected_reason)
            return result

        # 2. Secret scan
        if not secrets_clean(repo_path):
            result.rejected_reason = "secret_detected"
            log.info("[rust_pipeline] rejected %s — secrets detected", repo_path)
            return result

        # 3. Build script safety gate
        build_script_safety = self._check_build_script_safety(repo_path)
        if not build_script_safety.safe:
            result.rejected_reason = f"malicious_build_rs:{build_script_safety.reason}"
            log.warning("[rust_pipeline] rejected %s — %s", repo_path, result.rejected_reason)
            return result

        # 4. Extract repair tasks (baseline check is inside extractor)
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
    # Gate: build.rs safety
    # ------------------------------------------------------------------

    def _check_build_script_safety(self, repo_path: Path) -> BuildScriptSafetyResult:
        """
        Scan build.rs for injection / supply chain attack patterns.
        Legitimate build scripts use println!("cargo:rustc-cfg=...") and
        code generators. Malicious ones call out to curl|bash or dump env vars.
        """
        for build_rs in repo_path.rglob("build.rs"):
            try:
                content = build_rs.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scan_result = injection_scan(content, source=str(build_rs))
            if scan_result.risk in (InjectionRisk.HIGH, InjectionRisk.CRITICAL):
                finding = scan_result.findings[0] if scan_result.findings else None
                reason = f"injection_risk:{scan_result.risk.value}:{finding.pattern_name if finding else 'unknown'}"
                return BuildScriptSafetyResult(safe=False, reason=reason, script_path=str(build_rs))
        return BuildScriptSafetyResult(safe=True, reason="", script_path="")

    # ------------------------------------------------------------------
    # Extraction with injectable executor
    # ------------------------------------------------------------------

    def _extract_tasks(self, repo_path: Path) -> list[RustRepairTask]:
        """Run RustTaskExtractor, substituting our executor for subprocess."""
        extractor = RustTaskExtractor(repo_path, timeout=self._timeout)
        pipeline_self = self

        def _patched_run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
            return pipeline_self._executor(cmd, cwd or repo_path, pipeline_self._timeout)

        extractor._run = _patched_run  # type: ignore[method-assign]
        return extractor.extract_tasks(max_tasks=self._max_tasks)

    # ------------------------------------------------------------------
    # Corpus write
    # ------------------------------------------------------------------

    def _write_corpus_record(self, task: RustRepairTask, benchmark: str) -> str | None:
        """Write a RustRepairTask to corpus as a signed record."""
        try:
            from agents.base_agent import CorpusType

            payload = task.to_corpus_payload()
            input_hash = hashlib.blake2b(
                (task.mutated_line + task.failure_output).encode(),
                digest_size=16,
            ).hexdigest()
            output_hash = hashlib.blake2b(
                task.original_line.encode(),
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
            log.error("[rust_pipeline] failed to write corpus record %s: %s", task.task_id, e)
            return None

    # ------------------------------------------------------------------
    # Convenience factory for testing
    # ------------------------------------------------------------------

    @classmethod
    def make_test_task(
        cls,
        task_id: str = "test-rust-001",
        mutation_type: str = "unwrap_panic",
        failure_type: str = "panic",
        build_system: str = "cargo",
        failure_output: str = "thread 'main' panicked at 'determinex_none_inject', src/main.rs:42",
        original_line: str = "    let value = maybe.unwrap();",
        mutated_line: str = '    let value = maybe.expect("determinex_none_inject");',
        verdict: str = "pass",
    ) -> RustRepairTask:
        """Create a synthetic RustRepairTask for testing corpus write."""
        return RustRepairTask(
            task_id=task_id,
            source_file="src/main.rs",
            original_line=original_line,
            mutated_line=mutated_line,
            line_number=42,
            mutation_type=mutation_type,
            failure_output=failure_output,
            failure_type=failure_type,
            repair_patch=(
                "--- a/src/main.rs\n+++ b/src/main.rs\n"
                "@@ -42 +42 @@\n"
                f"-{mutated_line.strip()}\n"
                f"+{original_line.strip()}\n"
            ),
            build_system=build_system,
            verdict=verdict,
        )
