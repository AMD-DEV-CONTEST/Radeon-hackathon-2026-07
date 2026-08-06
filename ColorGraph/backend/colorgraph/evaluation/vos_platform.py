from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import torch
from pydantic import Field

from colorgraph.evaluation.models import StrictEvaluationModel

VOS_PLATFORM_AUDIT_VERSION = "colorgraph.vos-platform-prerequisite-audit/v1"

PlatformId = Literal["windows", "wsl2", "linux"]
AcceleratorId = Literal["cpu", "cuda", "rocm"]
PrerequisiteStatus = Literal["passed", "blocked", "failed"]


@dataclass(frozen=True)
class PlatformProbeResult:
    return_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    elapsed_ms: float = 0.0


PlatformProbeRunner = Callable[[list[str], float], PlatformProbeResult]


class HostPlatformEvidence(StrictEvaluationModel):
    operating_system: str
    python_version: str
    torch_version: str
    cuda_available: bool
    cuda_version: str | None
    hip_version: str | None
    gpu_name: str | None
    gpu_memory_mb: int | None = Field(default=None, ge=0)


class WSLPlatformEvidence(StrictEvaluationModel):
    distribution: str
    kernel: str | None
    wsl2_detected: bool
    gpu_visible: bool
    gpu_name: str | None
    driver_version: str | None
    gpu_memory_mb: int | None = Field(default=None, ge=0)
    python_version: str | None
    package_manager_available: bool
    torch_available: bool
    torch_version: str | None
    torch_cuda_available: bool
    torch_cuda_version: str | None
    status: PrerequisiteStatus
    blockers: list[str]
    probe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class VOSPlatformPrerequisiteRow(StrictEvaluationModel):
    platform: PlatformId
    accelerator: AcceleratorId
    status: PrerequisiteStatus
    scope: Literal["host_prerequisite"] = "host_prerequisite"
    blocker: str | None = None


class VOSPlatformPrerequisiteReport(StrictEvaluationModel):
    schema_version: str = VOS_PLATFORM_AUDIT_VERSION
    evaluator_version: str = VOS_PLATFORM_AUDIT_VERSION
    created_at: datetime
    status: Literal["passed", "partial", "blocked"]
    host: HostPlatformEvidence
    wsl: WSLPlatformEvidence | None
    matrix: list[VOSPlatformPrerequisiteRow]
    matrix_documented: bool
    wsl_cuda_prerequisites_passed: bool
    model_runtime_authorized: bool = False
    blockers: list[str]
    notes: list[str]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _default_probe_runner(
    command: list[str],
    timeout_seconds: float,
) -> PlatformProbeResult:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, OSError) as exc:
        return PlatformProbeResult(
            return_code=127,
            stderr=f"{type(exc).__name__}: {exc}",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return PlatformProbeResult(
            return_code=124,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    return PlatformProbeResult(
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def _result_text(result: PlatformProbeResult) -> str:
    return "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())


def _parse_gpu_csv(
    value: str,
) -> tuple[str | None, str | None, int | None]:
    first_line = next(
        (line.strip() for line in value.splitlines() if line.strip()),
        "",
    )
    fields = [field.strip() for field in first_line.split(",")]
    if len(fields) < 3:
        return None, None, None
    memory_digits = "".join(character for character in fields[2] if character.isdigit())
    return (
        fields[0] or None,
        fields[1] or None,
        int(memory_digits) if memory_digits else None,
    )


def _probe_wsl(
    distribution: str,
    *,
    runner: PlatformProbeRunner,
    timeout_seconds: float,
) -> WSLPlatformEvidence:
    commands = {
        "kernel": [
            "wsl.exe",
            "-d",
            distribution,
            "--",
            "uname",
            "-r",
        ],
        "gpu": [
            "wsl.exe",
            "-d",
            distribution,
            "--",
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader",
        ],
        "python": [
            "wsl.exe",
            "-d",
            distribution,
            "--",
            "python3",
            "--version",
        ],
        "package_manager": [
            "wsl.exe",
            "-d",
            distribution,
            "--",
            "python3",
            "-m",
            "pip",
            "--version",
        ],
        "torch_presence": [
            "wsl.exe",
            "-d",
            distribution,
            "--",
            "python3",
            "-c",
            ("import importlib.util;print('1' if importlib.util.find_spec('torch') else '0')"),
        ],
    }
    results = {probe_id: runner(command, timeout_seconds) for probe_id, command in commands.items()}
    kernel_result = results["kernel"]
    kernel = (
        kernel_result.stdout.strip()
        if kernel_result.return_code == 0 and kernel_result.stdout.strip()
        else None
    )
    wsl2_detected = bool(kernel and "microsoft-standard-wsl2" in kernel.lower())
    gpu_result = results["gpu"]
    gpu_name, driver_version, gpu_memory_mb = _parse_gpu_csv(gpu_result.stdout)
    gpu_visible = gpu_result.return_code == 0 and gpu_name is not None
    python_result = results["python"]
    python_version = _result_text(python_result) if python_result.return_code == 0 else None
    package_manager_available = results["package_manager"].return_code == 0
    torch_presence_result = results["torch_presence"]
    torch_available = (
        torch_presence_result.return_code == 0 and torch_presence_result.stdout.strip() == "1"
    )
    torch_version: str | None = None
    torch_cuda_available = False
    torch_cuda_version: str | None = None
    if torch_available:
        torch_details = runner(
            [
                "wsl.exe",
                "-d",
                distribution,
                "--",
                "python3",
                "-c",
                (
                    "import torch;"
                    "print('|'.join([torch.__version__,"
                    "'1' if torch.cuda.is_available() else '0',"
                    "str(torch.version.cuda or '')]))"
                ),
            ],
            timeout_seconds,
        )
        results["torch_details"] = torch_details
        if torch_details.return_code == 0:
            fields = torch_details.stdout.strip().split("|")
            if len(fields) == 3:
                torch_version = fields[0] or None
                torch_cuda_available = fields[1] == "1"
                torch_cuda_version = fields[2] or None

    blockers: list[str] = []
    if kernel_result.timed_out:
        blockers.append("wsl_probe_timed_out")
    elif kernel_result.return_code != 0:
        blockers.append("wsl_distribution_start_failed")
    if not wsl2_detected:
        blockers.append("wsl2_kernel_not_confirmed")
    if not gpu_visible:
        blockers.append("wsl_nvidia_gpu_not_visible")
    if python_version is None:
        blockers.append("wsl_python_missing")
    if not package_manager_available:
        blockers.append("wsl_python_package_manager_missing")
    if not torch_available:
        blockers.append("wsl_torch_missing")
    elif not torch_cuda_available:
        blockers.append("wsl_torch_cuda_unavailable")

    probe_payload = {
        probe_id: {
            "return_code": result.return_code,
            "timed_out": result.timed_out,
            "stdout_sha256": _sha256_text(result.stdout),
            "stderr_sha256": _sha256_text(result.stderr),
        }
        for probe_id, result in sorted(results.items())
    }
    status: PrerequisiteStatus
    if not blockers:
        status = "passed"
    elif kernel_result.return_code == 0:
        status = "blocked"
    else:
        status = "failed"
    return WSLPlatformEvidence(
        distribution=distribution,
        kernel=kernel,
        wsl2_detected=wsl2_detected,
        gpu_visible=gpu_visible,
        gpu_name=gpu_name,
        driver_version=driver_version,
        gpu_memory_mb=gpu_memory_mb,
        python_version=python_version,
        package_manager_available=package_manager_available,
        torch_available=torch_available,
        torch_version=torch_version,
        torch_cuda_available=torch_cuda_available,
        torch_cuda_version=torch_cuda_version,
        status=status,
        blockers=sorted(set(blockers)),
        probe_digest=_sha256_text(
            json.dumps(
                probe_payload,
                sort_keys=True,
                separators=(",", ":"),
            )
        ),
    )


def _host_evidence() -> HostPlatformEvidence:
    cuda_available = torch.cuda.is_available()
    gpu_name: str | None = None
    gpu_memory_mb: int | None = None
    if cuda_available:
        device = torch.cuda.current_device()
        gpu_name = torch.cuda.get_device_name(device)
        gpu_memory_mb = round(torch.cuda.get_device_properties(device).total_memory / 1024**2)
    return HostPlatformEvidence(
        operating_system=platform.platform(),
        python_version=sys.version.split()[0],
        torch_version=torch.__version__,
        cuda_available=cuda_available,
        cuda_version=torch.version.cuda,
        hip_version=torch.version.hip,
        gpu_name=gpu_name,
        gpu_memory_mb=gpu_memory_mb,
    )


def _row(
    platform_id: PlatformId,
    accelerator: AcceleratorId,
    *,
    passed: bool,
    blocker: str,
) -> VOSPlatformPrerequisiteRow:
    return VOSPlatformPrerequisiteRow(
        platform=platform_id,
        accelerator=accelerator,
        status="passed" if passed else "blocked",
        blocker=None if passed else blocker,
    )


def audit_vos_platform_prerequisites(
    output_path: str | Path,
    *,
    wsl_distribution: str | None = None,
    runner: PlatformProbeRunner | None = None,
    timeout_seconds: float = 10,
    created_at: datetime | None = None,
) -> VOSPlatformPrerequisiteReport:
    if timeout_seconds <= 0:
        raise ValueError("platform probe timeout must be positive")
    host = _host_evidence()
    system = platform.system().lower()
    selected_runner = runner or _default_probe_runner
    wsl = (
        _probe_wsl(
            wsl_distribution,
            runner=selected_runner,
            timeout_seconds=timeout_seconds,
        )
        if wsl_distribution
        else None
    )

    windows_host = system == "windows"
    linux_host = system == "linux"
    matrix = [
        _row(
            "windows",
            "cpu",
            passed=windows_host,
            blocker="Windows host was not tested by this report.",
        ),
        _row(
            "windows",
            "cuda",
            passed=windows_host and host.cuda_available,
            blocker="Windows CUDA host prerequisite is unavailable.",
        ),
        _row(
            "wsl2",
            "cuda",
            passed=wsl is not None and wsl.status == "passed",
            blocker=("WSL2 CUDA environment lacks a complete Python/PyTorch prerequisite chain."),
        ),
        _row(
            "linux",
            "cuda",
            passed=linux_host and host.cuda_available,
            blocker="Native Linux CUDA host was not tested by this report.",
        ),
        _row(
            "windows",
            "rocm",
            passed=windows_host and host.hip_version is not None,
            blocker="Windows ROCm runtime is unavailable.",
        ),
        _row(
            "linux",
            "rocm",
            passed=linux_host and host.hip_version is not None,
            blocker="Native Linux ROCm host was not tested by this report.",
        ),
    ]
    required_pairs = {
        ("windows", "cpu"),
        ("windows", "cuda"),
        ("wsl2", "cuda"),
        ("linux", "cuda"),
        ("windows", "rocm"),
        ("linux", "rocm"),
    }
    documented_pairs = {(row.platform, row.accelerator) for row in matrix}
    blockers: list[str] = []
    if wsl is None:
        blockers.append("wsl_distribution_not_requested")
    else:
        blockers.extend(wsl.blockers)
    if not any(row.platform == "linux" and row.status == "passed" for row in matrix):
        blockers.append("native_linux_runtime_not_tested")
    if not any(row.accelerator == "rocm" and row.status == "passed" for row in matrix):
        blockers.append("rocm_runtime_not_tested")
    blockers.extend(
        [
            "model_code_not_installed_and_hashed",
            "model_checkpoint_not_installed_and_hashed",
            "model_inference_not_executed",
        ]
    )
    passed_rows = sum(row.status == "passed" for row in matrix)
    report = VOSPlatformPrerequisiteReport(
        created_at=created_at or datetime.now(UTC),
        status=(
            "passed" if passed_rows == len(matrix) else ("partial" if passed_rows else "blocked")
        ),
        host=host,
        wsl=wsl,
        matrix=matrix,
        matrix_documented=required_pairs <= documented_pairs,
        wsl_cuda_prerequisites_passed=(wsl is not None and wsl.status == "passed"),
        blockers=sorted(set(blockers)),
        notes=[
            (
                "Rows describe host prerequisites only. They are not SAM, "
                "Cutie, or SEA-RAFT runtime compatibility results."
            ),
            (
                "Model authorization additionally requires immutable code and "
                "checkpoint hashes, license clearance, real inference, Gold "
                "metrics, and measured peak memory."
            ),
            "This audit does not install packages or download model artifacts.",
        ],
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
