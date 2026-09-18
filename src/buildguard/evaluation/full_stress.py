"""Full-system stress orchestration with explicit Windows/server semantics."""

from __future__ import annotations

import platform
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from buildguard.config import Settings
from buildguard.schemas.common import StrictSchema


class StressStageResult(StrictSchema):
    name: str
    success: bool
    latency_ms: float = Field(ge=0)
    peak_vram_ratio: float | None = Field(default=None, ge=0)
    oom: bool = False
    process_crash: bool = False
    evidence: list[str] = Field(default_factory=list)
    error: str | None = None


StressStage = Callable[[], StressStageResult]


@dataclass(frozen=True)
class FullStressAdapters:
    llm: StressStage
    reranker: StressStage
    ppe: StressStage
    api: StressStage
    sqlite_rag: StressStage
    gpu: StressStage

    def stages(self) -> dict[str, StressStage]:
        return {
            "llm": self.llm,
            "reranker": self.reranker,
            "ppe": self.ppe,
            "api": self.api,
            "sqlite_rag": self.sqlite_rag,
            "gpu": self.gpu,
        }


class FullStressResult(StrictSchema):
    status: Literal["PASS", "FAIL", "SERVER_VALIDATION_REQUIRED"]
    peak_vram_ratio: float | None = Field(default=None, ge=0)
    llm_success: bool = False
    reranker_success: bool = False
    ppe_success: bool = False
    api_success: bool = False
    oom: bool = False
    process_crash: bool = False
    latency: dict[str, float] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)


class FullStressRunner:
    def __init__(
        self,
        adapters: FullStressAdapters | None = None,
        *,
        platform_name: str | None = None,
    ) -> None:
        self.adapters = adapters
        self.platform_name = platform_name or platform.system()

    @staticmethod
    def _execute(stages: dict[str, StressStage]) -> dict[str, StressStageResult]:
        results: dict[str, StressStageResult] = {}
        with ThreadPoolExecutor(max_workers=len(stages)) as executor:
            futures = {executor.submit(stage): name for name, stage in stages.items()}
            for future in as_completed(futures):
                name = futures[future]
                started = time.perf_counter()
                try:
                    result = future.result()
                except (OSError, RuntimeError, ValueError) as exc:
                    message = str(exc)
                    result = StressStageResult(
                        name=name,
                        success=False,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        oom="out of memory" in message.casefold(),
                        process_crash="crash" in message.casefold(),
                        error=message,
                    )
                results[name] = result
        return results

    def run(self) -> FullStressResult:
        if self.platform_name.casefold() != "linux":
            evidence = [
                "Windows validates orchestration only; no GPU/performance result is accepted.",
                "SERVER_VALIDATION_REQUIRED",
            ]
            if self.adapters is not None:
                measured = self._execute(self.adapters.stages())
                evidence.extend(
                    f"fake_orchestration:{name}:{result.success}"
                    for name, result in sorted(measured.items())
                )
            return FullStressResult(
                status="SERVER_VALIDATION_REQUIRED",
                evidence=evidence,
            )
        if self.adapters is None:
            return FullStressResult(
                status="FAIL",
                evidence=["Real Linux stress adapters were not configured."],
            )
        results = self._execute(self.adapters.stages())
        vram_values = [
            item.peak_vram_ratio
            for item in results.values()
            if item.peak_vram_ratio is not None
        ]
        oom = any(item.oom for item in results.values())
        crash = any(item.process_crash for item in results.values())
        success = all(item.success for item in results.values()) and not oom and not crash
        return FullStressResult(
            status="PASS" if success else "FAIL",
            peak_vram_ratio=max(vram_values) if vram_values else None,
            llm_success=results["llm"].success,
            reranker_success=results["reranker"].success,
            ppe_success=results["ppe"].success,
            api_success=results["api"].success,
            oom=oom,
            process_crash=crash,
            latency={name: item.latency_ms for name, item in sorted(results.items())},
            evidence=[
                evidence
                for item in results.values()
                for evidence in item.evidence
            ]
            + [
                f"{name}: {item.error}"
                for name, item in sorted(results.items())
                if item.error
            ],
        )


def create_server_adapters(settings: Settings) -> FullStressAdapters:
    """Build real local adapters. Call only on the AMD Linux server."""
    import httpx

    from buildguard.llm.base import ChatMessage
    from buildguard.llm.openai_compatible import OpenAICompatibleLocalBackend
    from buildguard.monitoring.rocm_smi import RocmSmiMonitor
    from buildguard.rag.schemas import RagSearchInput
    from buildguard.rag.service import create_rag_service
    from buildguard.storage.database import Database
    from buildguard.vision.preprocessing import decode_image
    from buildguard.vision.schemas import SingleImageInspectionInput
    from buildguard.vision.service import create_vision_service

    configured = settings

    def stage(
        name: str,
        operation: Callable[[], tuple[bool, list[str], float | None]],
    ) -> StressStageResult:
        started = time.perf_counter()
        try:
            success, evidence, vram = operation()
            return StressStageResult(
                name=name,
                success=success,
                latency_ms=(time.perf_counter() - started) * 1000,
                peak_vram_ratio=vram,
                evidence=evidence,
            )
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            message = str(exc)
            return StressStageResult(
                name=name,
                success=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                oom="out of memory" in message.casefold(),
                process_crash="crash" in message.casefold(),
                error=message,
            )

    def llm_operation() -> tuple[bool, list[str], None]:
        backend = OpenAICompatibleLocalBackend(
            configured.llm, configured.permissions
        )
        try:
            response = backend.chat(
                [
                    ChatMessage(
                        role="user",
                        content=("local construction safety context " * 2400),
                    )
                ],
                profile="normal_dialogue",
            )
        finally:
            backend.close()
        tokens = response.metrics.completion_tokens
        return (
            512 <= tokens <= 1024,
            [f"llm_completion_tokens={tokens}"],
            None,
        )

    def reranker_operation() -> tuple[bool, list[str], None]:
        rag = create_rag_service(configured)
        ranked = rag.retriever.rank(
            RagSearchInput(query="construction safety requirements", top_k=20),
            20,
        )
        return len(ranked) >= 20, [f"reranked_candidates={len(ranked)}"], None

    def ppe_operation() -> tuple[bool, list[str], None]:
        extensions = {".jpg", ".jpeg", ".png"}
        sample = next(
            (
                path
                for path in configured.competition.ppe_dataset_dir.rglob("*")
                if path.is_file() and path.suffix.casefold() in extensions
            ),
            None,
        )
        if sample is None:
            raise ValueError("No PPE stress image is available")
        decoded = decode_image(sample)
        if decoded.width < 1920 or decoded.height < 1080:
            raise ValueError("PPE stress image must be at least 1080p")
        result = create_vision_service(configured).inspect_single(
            SingleImageInspectionInput(image_path=sample)
        )
        return result.summary.success, [f"ppe_image={sample}"], None

    def api_operation() -> tuple[bool, list[str], None]:
        url = f"{str(configured.services.api_base_url).rstrip('/')}/health"
        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        healthy = response.json().get("status") == "ok"
        return healthy, [f"api_health={response.status_code}"], None

    def sqlite_rag_operation() -> tuple[bool, list[str], None]:
        database = Database(configured.app.database_path)
        database_ok = bool(database.check()["ok"])
        rag = create_rag_service(configured)
        index_ok = bool(rag.validate_index()["valid"])
        return (
            database_ok and index_ok,
            [f"database={database_ok}", f"rag_index={index_ok}"],
            None,
        )

    def gpu_operation() -> tuple[bool, list[str], float | None]:
        snapshot = RocmSmiMonitor(
            configured.monitoring.command_timeout_seconds
        ).snapshot()
        ratios = [
            gpu.memory_used_mb / gpu.memory_total_mb
            for gpu in snapshot.gpus
            if gpu.memory_used_mb is not None
            and gpu.memory_total_mb is not None
            and gpu.memory_total_mb > 0
        ]
        ratio = max(ratios) if ratios else None
        return (
            snapshot.available and bool(snapshot.gpus) and ratio is not None,
            [f"gpu_count={len(snapshot.gpus)}"],
            ratio,
        )

    return FullStressAdapters(
        llm=lambda: stage("llm", llm_operation),
        reranker=lambda: stage("reranker", reranker_operation),
        ppe=lambda: stage("ppe", ppe_operation),
        api=lambda: stage("api", api_operation),
        sqlite_rag=lambda: stage("sqlite_rag", sqlite_rag_operation),
        gpu=lambda: stage("gpu", gpu_operation),
    )
