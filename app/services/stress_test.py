"""Stage J — Stress Test Tool.

Generates configurable load to validate:
- Large file processing (synthetic file generation)
- Batch file processing (many concurrent imports)
- Long context generation (max token prompts)
- Multi-project concurrency (parallel project workloads)

Can be used as a module or standalone CLI via ``python -m app.services.stress_test``.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import random
import string
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger("projectpack.stress_test")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class StressConfig:
    """Configuration for a stress test run."""

    large_file_count: int = 1
    large_file_size_mb: int = 10
    batch_file_count: int = 20
    batch_file_size_kb: int = 50
    long_context_prompt_tokens: int = 4000
    long_context_requests: int = 5
    multi_project_count: int = 4
    multi_project_requests_per_project: int = 10
    warmup_iterations: int = 1
    output_dir: Path | None = None


@dataclass
class StressResult:
    """Results from a single stress test phase."""

    phase: str = ""
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    total_duration_seconds: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    throughput_requests_per_sec: float = 0.0
    peak_vram_mb: float = 0.0
    avg_vram_mb: float = 0.0
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StressReport:
    """Aggregated stress test report."""

    config: StressConfig = field(default_factory=StressConfig)
    results: list[StressResult] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    overall_status: str = "unknown"

    @property
    def duration_seconds(self) -> float:
        return self.finished_at - self.started_at

    @property
    def total_requests(self) -> int:
        return sum(r.total_requests for r in self.results)

    @property
    def total_successful(self) -> int:
        return sum(r.successful for r in self.results)


# ---------------------------------------------------------------------------
# Stress Test Runner
# ---------------------------------------------------------------------------


class StressTestRunner:
    """Executes stress tests phases against the application."""

    def __init__(
        self,
        config: StressConfig,
        *,
        llm_call: Callable[..., Coroutine[Any, Any, str]] | None = None,
        embedding_call: Callable[..., Coroutine[Any, Any, list[list[float]]]] | None = None,
        file_import: Callable[..., Coroutine[Any, Any, dict]] | None = None,
    ) -> None:
        self._config = config
        self._llm_call = llm_call
        self._embedding_call = embedding_call
        self._file_import = file_import

    # ------------------------------------------------------------------
    # Phase 1: Large file stress
    # ------------------------------------------------------------------

    async def stress_large_files(self) -> StressResult:
        """Generate and process large synthetic files."""
        logger.info("Starting large file stress test...")
        latencies: list[float] = []
        errors: list[str] = []
        t0 = time.perf_counter()

        for i in range(self._config.large_file_count):
            content = self._generate_text_file(self._config.large_file_size_mb)
            file_name = f"stress_large_{i}.txt"
            t1 = time.perf_counter()
            try:
                if self._file_import:
                    await self._file_import(
                        project_id=f"stress-large-{i}",
                        file_name=file_name,
                        content=content,
                    )
                latencies.append((time.perf_counter() - t1) * 1000)
            except Exception as exc:
                errors.append(str(exc))

        total_duration = time.perf_counter() - t0
        return self._build_result(
            "large_files",
            self._config.large_file_count,
            latencies,
            errors,
            total_duration,
        )

    # ------------------------------------------------------------------
    # Phase 2: Batch file stress
    # ------------------------------------------------------------------

    async def stress_batch_files(self) -> StressResult:
        """Process many small files concurrently."""
        logger.info("Starting batch file stress test...")
        latencies: list[float] = []
        errors: list[str] = []
        t0 = time.perf_counter()

        async def process_one(i: int) -> float:
            content = self._generate_text_file_kb(self._config.batch_file_size_kb)
            t1 = time.perf_counter()
            if self._file_import:
                await self._file_import(
                    project_id="stress-batch",
                    file_name=f"batch_{i}.txt",
                    content=content,
                )
            return (time.perf_counter() - t1) * 1000

        tasks = [
            process_one(i) for i in range(self._config.batch_file_count)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                errors.append(str(r))
            else:
                latencies.append(r)

        total_duration = time.perf_counter() - t0
        return self._build_result(
            "batch_files",
            self._config.batch_file_count,
            latencies,
            errors,
            total_duration,
        )

    # ------------------------------------------------------------------
    # Phase 3: Long context stress
    # ------------------------------------------------------------------

    async def stress_long_context(self) -> StressResult:
        """Send prompts approaching max context length."""
        logger.info("Starting long context stress test...")
        latencies: list[float] = []
        errors: list[str] = []
        t0 = time.perf_counter()

        long_prompt = self._generate_long_prompt(
            self._config.long_context_prompt_tokens
        )

        for i in range(self._config.long_context_requests):
            t1 = time.perf_counter()
            try:
                if self._llm_call:
                    await self._llm_call(
                        messages=[{"role": "user", "content": long_prompt}],
                        max_tokens=256,
                    )
                latencies.append((time.perf_counter() - t1) * 1000)
            except Exception as exc:
                errors.append(str(exc))

        total_duration = time.perf_counter() - t0
        return self._build_result(
            "long_context",
            self._config.long_context_requests,
            latencies,
            errors,
            total_duration,
        )

    # ------------------------------------------------------------------
    # Phase 4: Multi-project concurrency
    # ------------------------------------------------------------------

    async def stress_multi_project(self) -> StressResult:
        """Run LLM calls across multiple projects concurrently."""
        logger.info("Starting multi-project concurrency stress test...")
        latencies: list[float] = []
        errors: list[str] = []
        t0 = time.perf_counter()

        total_requests = (
            self._config.multi_project_count
            * self._config.multi_project_requests_per_project
        )

        async def run_project_requests(project_idx: int) -> list[float]:
            project_latencies: list[float] = []
            for req_idx in range(self._config.multi_project_requests_per_project):
                t1 = time.perf_counter()
                try:
                    if self._llm_call:
                        await self._llm_call(
                            messages=[
                                {
                                    "role": "user",
                                    "content": f"Summarize project {project_idx}, request {req_idx}: Hello, this is a concurrency test.",
                                }
                            ],
                            max_tokens=64,
                            project_id=f"stress-multi-{project_idx}",
                        )
                    project_latencies.append(
                        (time.perf_counter() - t1) * 1000
                    )
                except Exception as exc:
                    errors.append(f"p{project_idx}r{req_idx}: {exc}")
            return project_latencies

        tasks = [
            run_project_requests(i)
            for i in range(self._config.multi_project_count)
        ]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in all_results:
            if isinstance(r, Exception):
                errors.append(str(r))
            else:
                latencies.extend(r)

        total_duration = time.perf_counter() - t0
        return self._build_result(
            "multi_project",
            total_requests,
            latencies,
            errors,
            total_duration,
        )

    # ------------------------------------------------------------------
    # Run all phases
    # ------------------------------------------------------------------

    async def run_all(self) -> StressReport:
        """Execute all stress test phases and return a full report."""
        report = StressReport(config=self._config)
        report.started_at = time.perf_counter()

        phases = [
            self.stress_large_files,
            self.stress_batch_files,
            self.stress_long_context,
            self.stress_multi_project,
        ]

        for phase in phases:
            try:
                result = await phase()
                report.results.append(result)
            except Exception as exc:
                logger.error("Stress test phase failed: %s", exc)
                report.results.append(
                    StressResult(
                        phase="error",
                        errors=[str(exc)],
                    )
                )

        report.finished_at = time.perf_counter()
        report.overall_status = (
            "pass"
            if all(r.failed == 0 for r in report.results)
            else "partial"
            if any(r.successful > 0 for r in report.results)
            else "fail"
        )
        return report

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_text_file(size_mb: int) -> str:
        """Generate a text file of approximately *size_mb* MB."""
        chars_per_line = 80
        lines_per_mb = (1024 * 1024) // chars_per_line
        total_lines = lines_per_mb * size_mb

        lines: list[str] = []
        for i in range(total_lines):
            line = f"[{i:08d}] " + "".join(
                random.choices(string.ascii_letters + string.digits, k=70)
            )
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _generate_text_file_kb(size_kb: int) -> str:
        return StressTestRunner._generate_text_file(
            max(1, size_kb // 1024)
        )

    @staticmethod
    def _generate_long_prompt(target_tokens: int) -> str:
        """Generate a prompt approximately *target_tokens* tokens long.

        Uses word repetition as a rough approximation (~0.75 tokens per word).
        """
        words_needed = int(target_tokens / 0.75)
        base = "The quick brown fox jumps over the lazy dog. "
        repeats = words_needed // 10
        return base * repeats

    @staticmethod
    def _build_result(
        phase: str,
        total: int,
        latencies: list[float],
        errors: list[str],
        duration: float,
    ) -> StressResult:
        successful = len(latencies)
        failed = len(errors)

        if latencies:
            sorted_lat = sorted(latencies)
            p50 = sorted_lat[len(sorted_lat) // 2]
            p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
            p99 = sorted_lat[int(len(sorted_lat) * 0.99)]
            avg = sum(latencies) / len(latencies)
        else:
            p50 = p95 = p99 = avg = 0.0

        throughput = total / max(duration, 0.001)

        return StressResult(
            phase=phase,
            total_requests=total,
            successful=successful,
            failed=failed,
            total_duration_seconds=round(duration, 3),
            avg_latency_ms=round(avg, 1),
            p50_latency_ms=round(p50, 1),
            p95_latency_ms=round(p95, 1),
            p99_latency_ms=round(p99, 1),
            throughput_requests_per_sec=round(throughput, 2),
            errors=errors,
        )

    def print_report(self, report: StressReport) -> str:
        """Format a stress test report as a readable string."""
        lines = [
            "=" * 60,
            "  STRESS TEST REPORT",
            "=" * 60,
            f"  Duration:    {report.duration_seconds:.2f}s",
            f"  Status:      {report.overall_status}",
            f"  Requests:    {report.total_requests} ({report.total_successful} ok)",
            "-" * 60,
        ]
        for r in report.results:
            lines.extend([
                f"\n  Phase: {r.phase}",
                f"    Requests:  {r.total_requests} (ok={r.successful}, fail={r.failed})",
                f"    Latency:   avg={r.avg_latency_ms:.1f}ms p50={r.p50_latency_ms:.1f}ms p95={r.p95_latency_ms:.1f}ms p99={r.p99_latency_ms:.1f}ms",
                f"    Throughput: {r.throughput_requests_per_sec:.2f} req/s",
                f"    Duration:  {r.total_duration_seconds:.2f}s",
            ])
            if r.errors:
                lines.append(f"    Errors ({len(r.errors)}):")
                for e in r.errors[:5]:
                    lines.append(f"      - {e[:120]}")
                if len(r.errors) > 5:
                    lines.append(f"      ... and {len(r.errors) - 5} more")
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _main() -> None:
    """Standalone stress test entry point."""
    config = StressConfig(
        large_file_count=1,
        large_file_size_mb=5,
        batch_file_count=10,
        long_context_prompt_tokens=2000,
        long_context_requests=3,
        multi_project_count=2,
        multi_project_requests_per_project=5,
    )

    async def mock_llm(**kwargs: Any) -> str:
        await asyncio.sleep(0.1)
        return "Mock LLM response"

    async def mock_embedding(**kwargs: Any) -> list[list[float]]:
        await asyncio.sleep(0.05)
        return [[0.1] * 384]

    async def mock_import(**kwargs: Any) -> dict:
        await asyncio.sleep(0.2)
        return {"status": "ok"}

    runner = StressTestRunner(
        config,
        llm_call=mock_llm,
        embedding_call=mock_embedding,
        file_import=mock_import,
    )

    report = await runner.run_all()
    print(runner.print_report(report))


if __name__ == "__main__":
    asyncio.run(_main())
