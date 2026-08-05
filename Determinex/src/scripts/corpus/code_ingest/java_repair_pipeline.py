"""
Java repair pipeline — license-gated, safety-checked, corpus-signed.

Wraps JavaTaskExtractor with:
  - License gate: only green-bucket repos enter extraction
  - POM safety gate: reject repos with injection patterns in build files
  - CorpusManager integration: every repair task written as HMAC-signed record
  - Injectable executor: subprocess calls are replaceable for testing

Usage (production):
    cm = CorpusManager(root=Path("T:/determinex_corpus"))
    pipeline = JavaRepairPipeline(corpus_manager=cm)
    count = pipeline.process_repo(Path("/repos/my-project"), "java_corpus")

Usage (testing):
    def fake_exec(cmd, cwd, timeout):
        if "baseline" in cwd.name:
            return (0, "BUILD SUCCESS", "")
        return (1, "", "NullPointerException at Foo.java:42")

    pipeline = JavaRepairPipeline(corpus_manager=cm, executor=fake_exec)
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.prompt_injection_detector import InjectionRisk
from agents.prompt_injection_detector import scan as injection_scan

from corpus.code_ingest.java_task_extractor import JavaRepairTask, JavaTaskExtractor
from corpus.code_ingest.license_detector import detect
from corpus.code_ingest.secret_scanner import is_clean as secrets_clean

log = logging.getLogger(__name__)

# Executor type: (cmd, cwd, timeout) → (returncode, stdout, stderr)
Executor = Callable[[list[str], Path, int], tuple[int, str, str]]


def _default_executor(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError as e:
        return -2, "", str(e)


@dataclass
class PipelineResult:
    repo_path: str
    tasks_extracted: int
    tasks_written: int
    rejected_reason: str = ""  # non-empty if repo was rejected before extraction
    license_spdx: str = ""
    license_bucket: str = ""
    task_ids: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.rejected_reason


@dataclass
class PomSafetyResult:
    safe: bool
    reason: str
    pom_path: str


class JavaRepairPipeline:
    """
    Full pipeline: license gate → pom safety → mutation → corpus write.

    Args:
        corpus_manager: CorpusManager instance for writing signed records.
        executor: Optional callable replacing subprocess. Signature:
            (cmd: list[str], cwd: Path, timeout: int) → (rc, stdout, stderr)
        max_tasks_per_repo: Maximum repair tasks to extract per repo.
        build_timeout: Seconds to wait for Maven/Gradle.
        source_benchmark: Default benchmark label for corpus records.
    """

    def __init__(
        self,
        corpus_manager: Any,
        executor: Executor | None = None,
        max_tasks_per_repo: int = 10,
        build_timeout: int = 120,
        source_benchmark: str = "java_corpus",
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
        """
        Run the full pipeline on a Java repo.
        Returns PipelineResult describing what happened.
        """
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
            log.info("[java_pipeline] rejected %s — %s", repo_path, result.rejected_reason)
            return result

        # 2. Secret scan
        if not secrets_clean(repo_path):
            result.rejected_reason = "secret_detected"
            log.info("[java_pipeline] rejected %s — secrets detected", repo_path)
            return result

        # 3. POM safety gate
        pom_safety = self._check_pom_safety(repo_path)
        if not pom_safety.safe:
            result.rejected_reason = f"malicious_pom:{pom_safety.reason}"
            log.warning("[java_pipeline] rejected %s — %s", repo_path, result.rejected_reason)
            return result

        # 4. Extract repair tasks via JavaTaskExtractor (with our executor)
        tasks = self._extract_tasks(repo_path)
        result.tasks_extracted = len(tasks)

        # 5. Write each task to corpus
        for task in tasks:
            task_id = self._write_corpus_record(task, benchmark)
            if task_id:
                result.task_ids.append(task_id)
                result.tasks_written += 1

        return result

    # ------------------------------------------------------------------
    # Gate implementations
    # ------------------------------------------------------------------

    def _check_pom_safety(self, repo_path: Path) -> PomSafetyResult:
        """Scan all pom.xml files for prompt injection / supply chain attacks."""
        for pom in repo_path.rglob("pom.xml"):
            try:
                content = pom.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            scan_result = injection_scan(content, source=str(pom))
            if scan_result.risk in (InjectionRisk.HIGH, InjectionRisk.CRITICAL):
                return PomSafetyResult(
                    safe=False,
                    reason=f"injection_risk:{scan_result.risk.value}:{scan_result.findings[0].pattern_name if scan_result.findings else 'unknown'}",
                    pom_path=str(pom),
                )
        return PomSafetyResult(safe=True, reason="", pom_path="")

    # ------------------------------------------------------------------
    # Extraction with injectable executor
    # ------------------------------------------------------------------

    def _extract_tasks(self, repo_path: Path) -> list[JavaRepairTask]:
        """Run JavaTaskExtractor, substituting our executor for subprocess."""
        extractor = JavaTaskExtractor(repo_path, timeout=self._timeout)
        # Patch the extractor's _run method to use our executor
        pipeline_self = self

        def _patched_run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
            return pipeline_self._executor(cmd, cwd or repo_path, pipeline_self._timeout)

        extractor._run = _patched_run  # type: ignore[method-assign]
        return extractor.extract_tasks(max_tasks=self._max_tasks)

    # ------------------------------------------------------------------
    # Corpus write
    # ------------------------------------------------------------------

    def _write_corpus_record(self, task: JavaRepairTask, benchmark: str) -> str | None:
        """Write a JavaRepairTask to corpus. Returns task_id or None on error."""
        try:
            from agents.base_agent import CorpusType

            payload = task.to_corpus_payload()
            input_hash = hashlib.blake2b(
                task.mutated_snippet.encode() + task.error_message.encode(),
                digest_size=16,
            ).hexdigest()
            output_hash = hashlib.blake2b(
                task.repair_patch.encode(),
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
            log.error("[java_pipeline] failed to write corpus record %s: %s", task.task_id, e)
            return None

    # ------------------------------------------------------------------
    # Convenience factory for testing
    # ------------------------------------------------------------------

    @classmethod
    def make_test_task(
        cls,
        task_id: str = "test-java-001",
        failure_type: str = "junit_failure",
        build_system: str = "maven",
        framework: str = "junit5",
        error_message: str = "NullPointerException at UserService.java:42",
        verdict: str = "pass",
    ) -> JavaRepairTask:
        """Create a synthetic JavaRepairTask for testing corpus write."""
        return JavaRepairTask(
            task_id=task_id,
            repo_path="/synthetic/repo",
            language="java",
            build_system=build_system,
            framework=framework,
            failure_type=failure_type,
            failing_test="UserServiceTest#testNullUser",
            error_message=error_message,
            mutated_file="src/main/java/UserService.java",
            original_snippet="if (user == null) throw new IllegalArgumentException();",
            mutated_snippet="if (false)",
            repair_patch="--- a/UserService.java\n+++ b/UserService.java\n@@ -42 @@\n-if (false)\n+if (user == null)",
            validator="mvn test" if build_system == "maven" else "gradle test",
            verdict=verdict,
        )
