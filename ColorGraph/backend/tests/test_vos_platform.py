from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from colorgraph.evaluation.vos_platform import (
    VOS_PLATFORM_AUDIT_VERSION,
    PlatformProbeResult,
    audit_vos_platform_prerequisites,
)


def _runner(
    *,
    torch_present: bool = True,
    torch_cuda: bool = True,
    pip_present: bool = True,
) -> Callable[[list[str], float], PlatformProbeResult]:
    def run(command: list[str], _: float) -> PlatformProbeResult:
        joined = " ".join(command)
        if "uname -r" in joined:
            return PlatformProbeResult(
                return_code=0,
                stdout="6.6.87.2-microsoft-standard-WSL2\n",
            )
        if "nvidia-smi" in joined:
            return PlatformProbeResult(
                return_code=0,
                stdout="NVIDIA GeForce RTX 5060 Ti, 610.47, 16311 MiB\n",
            )
        if "pip --version" in joined:
            return PlatformProbeResult(
                return_code=0 if pip_present else 1,
                stdout="pip 26.0\n" if pip_present else "",
            )
        if "importlib.util" in joined:
            return PlatformProbeResult(
                return_code=0,
                stdout="1\n" if torch_present else "0\n",
            )
        if "import torch" in joined:
            return PlatformProbeResult(
                return_code=0,
                stdout=("2.12.1+cu130|1|13.0\n" if torch_cuda else "2.12.1|0|\n"),
            )
        if "python3 --version" in joined:
            return PlatformProbeResult(
                return_code=0,
                stdout="Python 3.12.12\n",
            )
        raise AssertionError(f"unexpected platform probe: {command}")

    return run


def test_wsl_cuda_prerequisites_are_distinct_from_model_authorization(
    tmp_path: Path,
) -> None:
    report = audit_vos_platform_prerequisites(
        tmp_path / "report.json",
        wsl_distribution="Ubuntu-24.04",
        runner=_runner(),
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    assert report.schema_version == VOS_PLATFORM_AUDIT_VERSION
    assert report.matrix_documented is True
    assert report.wsl_cuda_prerequisites_passed is True
    assert report.model_runtime_authorized is False
    assert "model_inference_not_executed" in report.blockers
    assert report.wsl is not None
    assert report.wsl.gpu_memory_mb == 16311


def test_wsl_gpu_without_torch_or_package_manager_remains_blocked(
    tmp_path: Path,
) -> None:
    report = audit_vos_platform_prerequisites(
        tmp_path / "report.json",
        wsl_distribution="Ubuntu-22.04",
        runner=_runner(torch_present=False, pip_present=False),
    )

    assert report.wsl is not None
    assert report.wsl.status == "blocked"
    assert set(report.wsl.blockers) >= {
        "wsl_python_package_manager_missing",
        "wsl_torch_missing",
    }
    wsl_row = next(row for row in report.matrix if row.platform == "wsl2")
    assert wsl_row.status == "blocked"


def test_failed_wsl_start_is_reported_without_claiming_compatibility(
    tmp_path: Path,
) -> None:
    def failed_runner(
        _: list[str],
        __: float,
    ) -> PlatformProbeResult:
        return PlatformProbeResult(
            return_code=1,
            stderr="distribution unavailable",
        )

    report = audit_vos_platform_prerequisites(
        tmp_path / "report.json",
        wsl_distribution="missing",
        runner=failed_runner,
    )

    assert report.wsl is not None
    assert report.wsl.status == "failed"
    assert "wsl_distribution_start_failed" in report.blockers
    assert report.wsl_cuda_prerequisites_passed is False


def test_platform_probe_timeout_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        audit_vos_platform_prerequisites(
            tmp_path / "report.json",
            timeout_seconds=0,
        )
