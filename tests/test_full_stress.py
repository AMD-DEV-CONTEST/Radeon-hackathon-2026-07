from collections.abc import Callable

from buildguard.evaluation.full_stress import (
    FullStressAdapters,
    FullStressRunner,
    StressStageResult,
)


def _stage(
    name: str,
    *,
    success: bool = True,
    vram: float | None = None,
    oom: bool = False,
) -> Callable[[], StressStageResult]:
    return lambda: StressStageResult(
        name=name,
        success=success,
        latency_ms=1,
        peak_vram_ratio=vram,
        oom=oom,
        evidence=[f"{name}=measured"],
    )


def _adapters(
    *, failed: str | None = None, oom: bool = False
) -> FullStressAdapters:
    return FullStressAdapters(
        llm=_stage("llm", success=failed != "llm", oom=oom),
        reranker=_stage("reranker", success=failed != "reranker"),
        ppe=_stage("ppe", success=failed != "ppe"),
        api=_stage("api", success=failed != "api"),
        sqlite_rag=_stage("sqlite_rag", success=failed != "sqlite_rag"),
        gpu=_stage("gpu", success=failed != "gpu", vram=0.75),
    )


def test_windows_never_reports_fake_stress_as_passed() -> None:
    report = FullStressRunner(
        _adapters(),
        platform_name="Windows",
    ).run()

    assert report.status == "SERVER_VALIDATION_REQUIRED"
    assert report.peak_vram_ratio is None
    assert report.llm_success is False
    assert report.reranker_success is False
    assert report.ppe_success is False
    assert report.api_success is False
    assert any("fake_orchestration" in item for item in report.evidence)


def test_linux_real_adapter_results_produce_pass_and_metrics() -> None:
    report = FullStressRunner(_adapters(), platform_name="Linux").run()

    assert report.status == "PASS"
    assert report.peak_vram_ratio == 0.75
    assert report.llm_success
    assert report.reranker_success
    assert report.ppe_success
    assert report.api_success
    assert set(report.latency) == {
        "api",
        "gpu",
        "llm",
        "ppe",
        "reranker",
        "sqlite_rag",
    }


def test_linux_failure_or_oom_cannot_pass() -> None:
    failed = FullStressRunner(
        _adapters(failed="ppe"),
        platform_name="Linux",
    ).run()
    oom = FullStressRunner(
        _adapters(oom=True),
        platform_name="Linux",
    ).run()

    assert failed.status == "FAIL"
    assert failed.ppe_success is False
    assert oom.status == "FAIL"
    assert oom.oom is True
